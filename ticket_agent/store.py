"""All mutations are transactional; no LLM-generated SQL is executed."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .models import Analysis

KB = [
    {"id": "KB-001", "title": "Login and password reset", "text": "Use the official Forgot password page. Check the spam folder. Never request passwords or one-time codes. Escalate persistent lockouts to the access team."},
    {"id": "KB-002", "title": "Duplicate billing or refund", "text": "Ask for invoice reference and transaction date, never full card details. Billing staff must verify duplicate charges and approve refunds."},
    {"id": "KB-003", "title": "Service outage or error", "text": "Collect error message, timestamp, affected users and service name. Engineering checks service health. Do not claim an outage is fixed without verification."},
    {"id": "KB-004", "title": "Suspected account compromise", "text": "Escalate to the security team. Advise use of official account recovery. Do not ask for secrets or promise containment before investigation."},
]
TEAMS = {"access": "access-support", "billing": "billing-support", "technical": "engineering-support", "security": "security-response", "other": "general-support"}
RANK = {"low": 0, "normal": 1, "high": 2, "urgent": 3}


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    path = Path(os.getenv("TICKET_DB", "data/tickets.db")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS tickets (
          id INTEGER PRIMARY KEY, subject TEXT NOT NULL, body TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal',
          team TEXT NOT NULL DEFAULT 'unassigned', version INTEGER NOT NULL DEFAULT 1,
          processed_version INTEGER NOT NULL DEFAULT 0, analysis TEXT,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, operation_key TEXT UNIQUE NOT NULL,
          ticket_id INTEGER NOT NULL, before_json TEXT NOT NULL,
          after_json TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')


def create(subject: str, body: str):
    if not subject.strip() or not body.strip() or len(subject) > 300 or len(body) > 12000:
        raise ValueError("Provide a subject (1–300 chars) and body (1–12000 chars)")
    with connect() as db:
        cur = db.execute("INSERT INTO tickets(subject,body,updated_at) VALUES (?,?,?)", (subject, body, now()))
        return cur.lastrowid


def get(ticket_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        if not row:
            raise ValueError("Ticket not found")
        return dict(row)


def pending(limit: int = 100):
    with connect() as db:
        return [dict(x) for x in db.execute("SELECT * FROM tickets WHERE status='open' AND processed_version < version ORDER BY id LIMIT ?", (max(1, min(limit, 100)),))]


def search(query: str):
    words = {w.strip('.,?!:').lower() for w in query.split() if len(w) > 2}
    scored = [(sum(w in (x['title'] + ' ' + x['text']).lower() for w in words), x) for x in KB]
    return [x for score, x in sorted(scored, key=lambda p: p[0], reverse=True) if score > 0][:3]


def plan(ticket: dict, a: Analysis):
    # Evidence is checked against the actual ticket, not a model-provided ID.
    source = (ticket['subject'] + '\n' + ticket['body']).casefold()
    evidence_ok = all(e.strip() and e.casefold() in source for e in a.evidence)
    kb_ok = all(k in {x['id'] for x in KB} for k in a.kb_ids)
    review = a.needs_human or a.confidence < .85 or a.category in {'security', 'billing'} or not evidence_ok or not kb_ok
    # Model confidence is a routing heuristic, not a calibrated probability.
    priority = max([ticket['priority'], a.priority], key=RANK.get)
    if a.category == 'security':
        priority = 'urgent'
    return {"status": "review_required" if review else "open", "priority": priority,
            "team": TEAMS[a.category], "analysis": a.model_dump(),
            "policy": {"review_required": review, "evidence_valid": evidence_ok, "kb_ids_valid": kb_ok}}


def apply(ticket_id: int, expected_version: int, analysis: dict, dry_run: bool = True):
    a = Analysis.model_validate(analysis)
    key = hashlib.sha256(f"triage-v1:{ticket_id}:{expected_version}".encode()).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old_audit = db.execute('SELECT after_json FROM audit WHERE operation_key=?', (key,)).fetchone()
        if old_audit:
            return {"outcome": "already_applied", "result": json.loads(old_audit[0])}
        row = db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
        if row is None:
            raise ValueError('Ticket not found')
        before = dict(row)
        if before['version'] != expected_version:
            raise ValueError('Version conflict: re-read and analyse the latest ticket')
        if before['status'] != 'open' or before['processed_version'] >= expected_version:
            raise ValueError('Ticket is not eligible for automatic analysis')
        update = plan(before, a)
        if dry_run:
            return {"outcome": "preview", "ticket_id": ticket_id, "changes": update}
        version = expected_version + 1
        db.execute('UPDATE tickets SET status=?,priority=?,team=?,analysis=?,version=?,processed_version=?,updated_at=? WHERE id=?',
                   (update['status'], update['priority'], update['team'], json.dumps(update), version, version, now(), ticket_id))
        after = dict(db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone())
        db.execute('INSERT INTO audit(operation_key,ticket_id,before_json,after_json,created_at) VALUES (?,?,?,?,?)',
                   (key, ticket_id, json.dumps(before), json.dumps(after), now()))
        return {"outcome": "updated", "ticket_id": ticket_id, "changes": update, "version": version}


def human_update(ticket_id: int, expected_version: int, status: str, body: str | None = None):
    if status not in {'open', 'in_progress', 'resolved', 'closed'}:
        raise ValueError('Invalid status')
    if body is not None and not 1 <= len(body) <= 12000:
        raise ValueError('Body must contain 1–12000 characters')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
        if row is None or row['version'] != expected_version:
            raise ValueError('Missing ticket or version conflict')
        before = dict(row)
        db.execute('UPDATE tickets SET status=?,body=?,version=version+1,updated_at=? WHERE id=?',
                   (status, body if body is not None else row['body'], now(), ticket_id))
        after = dict(db.execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone())
        db.execute('INSERT INTO audit(operation_key,ticket_id,before_json,after_json,created_at) VALUES (?,?,?,?,?)',
                   (f'human:{ticket_id}:{expected_version}', ticket_id, json.dumps(before), json.dumps(after), now()))
        return after


def audit(ticket_id: int):
    with connect() as db:
        return [dict(x) for x in db.execute('SELECT * FROM audit WHERE ticket_id=? ORDER BY id', (ticket_id,))]
