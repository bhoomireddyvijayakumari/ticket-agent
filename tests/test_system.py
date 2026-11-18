import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch
from ticket_agent import store
from ticket_agent.models import Analysis


def sample(**changes):
    values = dict(summary='Login failure', category='access', priority='normal',
                  sentiment='negative', confidence=.95, evidence=['Login fails'],
                  suggested_steps=['Use official reset page'], kb_ids=['KB-001'],
                  draft_reply='Please try the official password reset page.', needs_human=False,
                  reason='Clear access issue supported by KB-001')
    values.update(changes)
    return Analysis(**values)


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'TICKET_DB': self.tmp.name + '/tickets.db'})
        self.env.start()
        store.init()
        self.id = store.create('Login fails', 'Password reset email not received.')

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_preview(self):
        self.assertEqual(store.apply(self.id, 1, sample().model_dump())['outcome'], 'preview')
        self.assertEqual(store.get(self.id)['version'], 1)
        self.assertEqual(store.audit(self.id), [])

    def test_idempotency(self):
        a = sample().model_dump()
        store.apply(self.id, 1, a, False)
        self.assertEqual(store.apply(self.id, 1, a, False)['outcome'], 'already_applied')
        self.assertEqual(len(store.audit(self.id)), 1)
        self.assertEqual(store.pending(), [])

    def test_conflict(self):
        store.human_update(self.id, 1, 'open', 'Updated issue')
        with self.assertRaisesRegex(ValueError, 'Version conflict'):
            store.apply(self.id, 1, sample().model_dump(), False)

    def test_uncertain(self):
        r = store.apply(self.id, 1, sample(confidence=.5).model_dump(), False)
        self.assertEqual(r['changes']['status'], 'review_required')

    def test_security(self):
        p = store.plan(store.get(self.id), sample(category='security'))
        self.assertEqual((p['status'], p['priority'], p['team']), ('review_required', 'urgent', 'security-response'))

    def test_grounding(self):
        self.assertTrue(store.plan(store.get(self.id), sample(evidence=['invented']))['policy']['review_required'])
        self.assertTrue(store.plan(store.get(self.id), sample(kb_ids=['KB-999']))['policy']['review_required'])

    def test_no_downgrade(self):
        ticket = store.get(self.id)
        ticket['priority'] = 'urgent'
        self.assertEqual(store.plan(ticket, sample())['priority'], 'urgent')

    def test_closed(self):
        store.human_update(self.id, 1, 'closed')
        with self.assertRaises(ValueError):
            store.apply(self.id, 2, sample().model_dump(), False)

    def test_schema(self):
        data = sample().model_dump()
        data['status'] = 'closed'
        with self.assertRaises(ValueError):
            store.apply(self.id, 1, data, False)

    def test_reopen(self):
        store.apply(self.id, 1, sample(needs_human=True).model_dump(), False)
        store.human_update(self.id, 2, 'open', 'Login fails after reset; investigate again.')
        self.assertEqual(len(store.pending()), 1)
        self.assertEqual(len(store.audit(self.id)), 2)

    def test_real_mcp(self):
        from ticket_agent.agent import run_batch, call
        async def deterministic(client, ticket):
            articles = await call(client, 'search_knowledge_base', {'query': 'password reset'})
            self.assertTrue(any(x['id'] == 'KB-001' for x in articles))
            return sample()
        result = asyncio.run(run_batch(apply=True, analyser=deterministic))
        self.assertEqual(result[0]['outcome'], 'updated')
        self.assertEqual(store.get(self.id)['team'], 'access-support')
        self.assertEqual(asyncio.run(run_batch(apply=True, analyser=deterministic)), [])

    def test_failure(self):
        from ticket_agent.agent import run_batch
        async def failed(client, ticket):
            raise TimeoutError()
        result = asyncio.run(run_batch(apply=True, analyser=failed))
        self.assertEqual(result[0]['outcome'], 'error')
        self.assertEqual(store.get(self.id)['version'], 1)

if __name__ == '__main__':
    unittest.main()
