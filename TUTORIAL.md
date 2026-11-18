# Build a ticket analysis agent: VS Code → LangChain + MCP → AWS

**Beginner workshop • GPT-4o mini • Python • Local first • Small AWS deployment**

This guide builds on the supplied ticket-agent project. Start with tiny programs,
learn what each component does, run the complete system locally, then move the
same application to AWS. All source files are included. You can read this document
in VS Code with **Open Preview** (right-click the Markdown tab).

Expected time: four sessions of about 90 minutes, plus time to create accounts.
These are teaching estimates. Do not move to the next milestone until its check passes.

## 0. What we are building

A customer says: “The password reset email never arrived. I cannot log in.”
Our system reads this ticket, retrieves relevant support guidance, classifies it,
drafts a reply, assigns a team and saves an internal analysis. It keeps a record
of what changed. It periodically checks for new tickets.

| Component | Plain-language role | Where it runs locally |
|---|---|---|
| VS Code | Editor and terminal where you work | Your laptop |
| CLI | Commands for creating, viewing and processing tickets | Your laptop |
| LangChain agent | Coordinates the model and its knowledge-search tool | Your laptop |
| GPT-4o mini | Interprets text and creates structured analysis | OpenAI API |
| MCP client | Sends tool requests to the server | Your laptop |
| MCP server | Exposes ticket and knowledge operations | Separate laptop process |
| SQLite | Stores tickets and audit records in one file | Your laptop |
| Policy | Checks the analysis before committing updates | MCP server |

**Local mode does not mean an offline language model.** Both the MCP client and
server run locally, but GPT-4o mini still needs internet access and an API key.
Later both Python processes and SQLite move to one AWS machine; the model stays
at OpenAI. We do not install GPT weights or rent a GPU.

The exact identifier is **`gpt-4o-mini`**, with letter “o”, not `gpt-40-mini`.
As checked on 31 October 2026, OpenAI marks this model deprecated. The tutorial
keeps your requested identifier, but first checks access. If your API account
cannot use it, choose an available model supporting tool calls and structured
output and change `OPENAI_MODEL`. That is a model change; rerun the examples and
evaluate its ticket decisions rather than assuming identical behaviour. [1]

## 1. Learn the four ideas before coding

**An LLM** reads text and predicts a useful response. By itself it cannot read our
SQLite file or update tickets.

**A tool** is a Python operation the application lets the model request. For
example, `search_knowledge_base("password reset")` returns approved guidance.

**An agent** uses a model to choose tool calls, observes their results, and produces
an answer. In this project the agent chooses knowledge searches. Application code
controls ticket selection and writes.

**MCP (Model Context Protocol)** is a standard way for a client to discover and call
operations offered by a server. We could call a Python function directly in a tiny
application; MCP becomes useful when tools live in a separate process or service
and multiple applications need the same interface.

A tool call is not the model executing Python. The model emits a tool name and
arguments. LangChain invokes our wrapper; the MCP client sends a request; the MCP
server executes the allowed Python function and returns its result.

We use **stdio transport**: the two processes communicate through input/output
pipes. There is no HTTP URL or port 8000 in this version. The client starts the
server automatically. You do not need two terminals to start them separately.

## 2. Prepare your computer and accounts

Install Python **3.12** and VS Code. Python 3.11+ is declared compatible, but the
supplied dependency snapshot was tested on Python 3.12/Linux. In VS Code install
the Microsoft **Python**, **Python Debugger**, and (for AWS later) **Remote - SSH**
extensions. You do not need GitHub Copilot.

You also need an OpenAI API project with model access and usable billing/credits.
Check the API dashboard rather than assuming a ChatGPT subscription alone covers
these calls. Do not paste your API key into a notebook output, chat or GitHub.
For the AWS stage, prepare an AWS account with billing access and permission to
create Lightsail resources; enable MFA for account access.

Download and extract this tutorial ZIP. In VS Code select **File → Open Folder**
and open its inner **ticket-agent** folder. You should see `pyproject.toml`,
`TUTORIAL.md`, `lessons`, `ticket_agent`, `tests` and `deploy`.

Choose **Terminal → New Terminal**. Commands below run from this project folder,
not from the inner `ticket_agent` package directory.

### Windows PowerShell

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

If activation is blocked by organizational policy, do not change machine-wide
policy. Use `.\.venv\Scripts\python.exe` in place of `python` and
`.\.venv\Scripts\ticket-agent.exe` in place of `ticket-agent` in later commands.

### macOS / Linux

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

`venv` creates a project-specific Python environment. Activation makes `python`
refer to that environment. It prevents this project's dependencies from mixing
with other projects. A new terminal may need activation again.

### Install the dependencies — both operating systems

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
python -m pip check
```

The first install uses exact package versions from our validated environment.
`-e .` installs the current project in editable mode, so saved source edits apply
without reinstalling. `--no-deps` avoids resolving the already installed packages
again. If a platform cannot use the lock file, install `python -m pip install -e .`
in a fresh virtual environment and run the tests before continuing.

In VS Code press Ctrl+Shift+P (Cmd+Shift+P on macOS), choose **Python: Select
Interpreter**, and select the project's `.venv` interpreter.

**Checkpoint:** `python -c "import langchain, mcp; print('Imports work')"` succeeds.
The MCP SDK is deliberately constrained to 1.x (`mcp<2`); this guide's FastMCP
imports follow that version. Do not upgrade to SDK 2.x without adapting code. [2]

## 3. Configure GPT-4o mini and make one call

Create `.env` by copying `.env.example` in VS Code. Enter:

```dotenv
OPENAI_API_KEY=your_actual_key_here
OPENAI_MODEL=gpt-4o-mini
TICKET_DB=./data/tickets.db
```

Do not include surrounding angle brackets. `.env` is configuration, not Python.
`load_dotenv()` reads it into environment variables. `.gitignore` excludes this
file. On macOS/Linux, restrict access with `chmod 600 .env`.

Open `lessons/01_check_model.py`. It does four things:

1. Loads the key and model name from `.env`.
2. Creates `ChatOpenAI`, LangChain's model interface.
3. Sends a tiny request with `model.invoke(...)`.
4. Prints the response and reported token usage, not your key.

Run:

```bash
python lessons/01_check_model.py
```

Expected response: `Ticket analyser is ready` (the exact wording may vary).
This is a real, billable API call. A 401 usually indicates a credential problem;
429 can mean quota or rate limits; model-not-found may mean unavailable model
access. Fix this now, before debugging the agent. We configured no retries in
this tiny diagnostic so a failed request does not quietly repeat.

## 4. Build the smallest MCP server

Open `lessons/02_tiny_server.py`. Its central section is:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP('first-ticket-server')

@mcp.tool()
def get_demo_ticket(ticket_id: int) -> dict:
    """Return a fictional support ticket for the MCP learning exercise."""
    return {'id': ticket_id, 'subject': 'Cannot log in',
            'body': 'The password reset email has not arrived.', 'status': 'open'}

if __name__ == '__main__':
    mcp.run(transport='stdio')
```

`FastMCP` manages protocol messages. `@mcp.tool()` registers the function so a
client can discover and call it. The type hint `ticket_id: int` describes an
integer argument. The docstring explains the operation to callers.

This toy function returns a fictional ticket for any supplied ID. It does not
query a database. The full server later validates that the ticket exists.

You can run `python lessons/02_tiny_server.py`, but it will appear to wait without
output: it is waiting for protocol messages. Stop it with Ctrl+C. For normal use,
run the client in the next step, which starts its own server process.

Do not add `print()` debugging to a stdio MCP server's stdout. It carries protocol
messages. Use logging to stderr if needed.

## 5. Build the smallest MCP client

Open `lessons/03_tiny_client.py`. Read these lines in order:

```python
params = StdioServerParameters(command=sys.executable, args=[str(server_path)])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as client:
        await client.initialize()
        catalog = await client.list_tools()
        result = await client.call_tool('get_demo_ticket', {'ticket_id': 101})
```

`sys.executable` uses the same virtual-environment Python for the server. `read`
and `write` are the communication pipes. `initialize()` establishes the MCP
session. `list_tools()` asks what the server offers. `call_tool()` asks it to run
one operation with supplied arguments. `async with` closes the session when the
block finishes, even if an exception occurs.

`async` and `await` let Python wait for external operations without treating them
as immediate local calculations. You do not need to master asynchronous programming
to run this example; keep the supplied structure intact.

Run:

```bash
python lessons/03_tiny_client.py
```

**Checkpoint:** you see `Available tools: ['get_demo_ticket']` and a JSON ticket
with ID 101. This test uses no LLM or API credits. You now have a local client and
a separate local server communicating through MCP.

Exercise: change the client's requested ID to 102 and rerun. Then change the toy
server's subject and observe the returned value. Restore the files afterwards.

## 6. Create persistent tickets with SQLite

The complete system lives in the `ticket_agent` package. SQLite is included with
Python, so no MySQL/PostgreSQL setup is necessary for this exercise.

```bash
ticket-agent init
ticket-agent seed
ticket-agent show 1
python lessons/04_inspect_database.py
```

`init` creates tables if missing. `seed` inserts six fictional tickets. On a fresh
database their IDs are 1–6; running seed again adds another six, so normally run
it once. `show` prints a ticket. The inspection lesson lists eligible open tickets.
The file `data/tickets.db` now persists your data between program runs.

If you prefer a completely new classroom database, change `TICKET_DB` to
`./data/classroom.db`, then initialize and seed it. This preserves your old data.

Read `store.py`, starting with `init()`, `create()`, `get()` and `pending()`.

| Ticket column | Meaning |
|---|---|
| id | Unique database identifier |
| subject / body | Customer's reported problem |
| status | open, review_required, in_progress, resolved or closed |
| priority / team | Operational routing fields |
| version | Revision number, increased when a ticket changes |
| processed_version | Latest revision handled by the automatic analyser |
| analysis | JSON containing analysis, draft reply and policy outcome |
| updated_at | UTC timestamp |

SQL queries use placeholders such as `WHERE id=?`, so values are passed as data.
The model never generates SQL. The `audit` table stores before/after snapshots.
This is a small single-machine database design, not a multi-tenant help-desk schema.

## 7. Define the analysis we want

Open `models.py`. `Analysis` is a Pydantic model: a declaration of allowed fields
and their types. For example:

```python
category: Literal['access', 'billing', 'technical', 'security', 'other']
priority: Literal['low', 'normal', 'high', 'urgent']
confidence: float = Field(ge=0, le=1)
```

`Literal` restricts choices. `Field(ge=0, le=1)` restricts a number to a range.
`extra='forbid'` rejects fields we did not define, such as a model-invented
`delete_all_tickets` operation. It does not prove the permitted text is correct.

Other fields contain a summary, sentiment, exact evidence excerpts, suggested
steps, article IDs, draft reply and whether human review is needed.

Example intent: for a login issue, produce `category='access'` and a reply suggesting
the official reset procedure. The model must not claim it reset the account itself.

## 8. Expose the real functions through MCP

Open `server.py`. Its tools are:

| MCP tool | What it does | Who calls it in our application |
|---|---|---|
| get_ticket | Reads one snapshot and version | Workflow |
| list_pending | Finds eligible tickets | Workflow |
| search_knowledge_base | Finds support articles by keywords | Agent via wrapper |
| apply_analysis | Validates and previews/commits analysis | Workflow |

The server delegates to `store.py`. This separation lets you later replace SQLite
with a real help-desk API while keeping the agent's conceptual workflow.

The knowledge base has four sample articles: access, billing, outages and security.
Search counts keyword matches. It is intentionally simple; it is not a vector
index or a full RAG system. Add your own verified guidance only after the baseline
works. The model should cite the returned article IDs.

## 9. Connect LangChain to the MCP search tool

Open `agent.py`. Inside `analyse()` we define:

```python
@tool
async def search_knowledge_base(query: str) -> str:
    """Search approved support guidance. Returns article IDs and text."""
    result = await call(client, 'search_knowledge_base', {'query': query})
    return json.dumps(result)
```

There are two tool interfaces here. `@tool` presents a tool to **LangChain**. Its
body calls an **MCP** operation. The wrapper is the bridge between them. Using an
explicit wrapper also makes it clear which MCP capability the model may use.
The model receives only this search tool, not the server's update tool.

The helper `call()` checks MCP errors and decodes responses. SDK 1.x may return
structured content or JSON text blocks; list responses need special handling.
This detail is already handled in the supplied tested code.

Next, the agent is constructed:

```python
model = ChatOpenAI(
    model=os.getenv('OPENAI_MODEL', 'gpt-4o-mini'),
    temperature=0, timeout=45, max_retries=2
)
agent = create_agent(
    model=model,
    tools=[search_knowledge_base],
    system_prompt=SYSTEM,
    response_format=ToolStrategy(Analysis)
)
```

`temperature=0` asks for less variation, not perfect determinism. `timeout` bounds
a provider request. `max_retries` permits limited retries for eligible failures.
`SYSTEM` describes the task and restrictions. `ToolStrategy(Analysis)` obtains a
response matching our schema through LangChain's structured-output mechanism. [3]

`agent.ainvoke(...)` runs the tool loop. The model can request search, receive
results and produce an analysis. We read `result['structured_response']`. A
recursion limit bounds agent steps; an outer timeout bounds total analysis time.
The prompt asks the model to search, but this is not a code-level guarantee that
every successful model answer includes a search. Inspect traces/tests when
extending the system; do not confuse a prompt instruction with enforcement.

## 10. Understand the update policy before turning it on

The model's response is a proposal. `store.plan()` applies deterministic rules:

- Map category to a permitted team.
- Never reduce an existing priority automatically.
- Route security to urgent priority and security-response.
- Require review for billing/security, low confidence, requested review, unknown
  article IDs or evidence excerpts not found in the ticket.
- Save the reply as an internal draft; never send it or resolve the ticket.

Confidence below 0.85 is a sample review rule. The score is self-reported, not a
calibrated probability. Exact quotes and valid article IDs do not establish that
an answer is factually correct. A model could misclassify a security ticket as
access; the category rule only sees the classification it receives.

`apply()` validates the schema, checks version/eligibility and uses a database
transaction. Either the ticket update and audit record both succeed, or neither
does. Its operation key identifies the source ticket revision, preventing duplicate
writes when the same operation is retried.

Example: the worker reads version 1, then a human updates the ticket to version 2.
The worker's version-1 proposal must be rejected so it cannot overwrite new facts.
This is called **optimistic concurrency control**.

## 11. Preview a complete analysis locally

```bash
ticket-agent run --id 1
```

The workflow reads the ticket through MCP, asks GPT-4o mini to analyse it, and
requests a preview from `apply_analysis`. Expected top-level outcome: `preview`.
You should see proposed status, priority, team, analysis and policy checks.

```bash
ticket-agent show 1
ticket-agent audit 1
```

**Checkpoint:** on the first preview, the ticket version is still 1 and the audit
list is empty. A preview consumes API tokens but does not write ticket changes.
Actual classifications and wording can vary; do not expect exact sample sentences.

For debugging, press F5 in VS Code and choose **Preview ticket 1 (calls OpenAI)**.
Set a breakpoint in `run_batch()` just after `analysis = await analyser(...)`.
Inspect the typed analysis. Do not inspect/share secret environment values.

## 12. Commit internal updates and inspect the audit

```bash
ticket-agent run --id 1 --apply
ticket-agent show 1
ticket-agent audit 1
```

`--apply` enables actual internal writes. This command performs fresh analysis,
not approval of an immutable earlier preview. On the first successful update,
outcome is `updated`, version becomes 2, and an audit row records the change.
The stored analysis includes the draft customer reply.

To process the remaining eligible tickets:

```bash
ticket-agent run --apply --limit 5
```

`--limit` is a ticket count, not a spending cap. Re-running batch mode skips
already processed revisions. Explicitly naming an already processed ticket can
still cause an unnecessary model call before eligibility rejection, so use batch
mode for routine operation.

Review the billing and security examples. They should require staff review if
correctly classified. Test the hostile-text ticket too: its words must not give
the model new powers. This is a behavioural evaluation, not proof of complete
prompt-injection protection.

## 13. Continuous operation and human review

```bash
ticket-agent watch --apply --interval 300 --limit 5
```

Every cycle processes up to five eligible tickets, then waits 300 seconds. No
model call is needed when there are no eligible tickets. The client starts a new
MCP server session each cycle. Stop the loop with Ctrl+C.

Open another VS Code terminal, activate `.venv` and add a new ticket:

```bash
ticket-agent add --subject "Checkout failed" --body "Customers see a 503 error during checkout."
```

Copy the ID printed by `add` and inspect it after the next cycle using
`ticket-agent show ID` (replace ID with the number). Its version/team should change.
A case awaiting review is not repeatedly analysed.

For a reviewed ticket, first inspect its current version. Example only:

```bash
ticket-agent show 2
ticket-agent edit 2 --version 2 --status in_progress
```

Use the version you actually observed. To request fresh analysis after new customer
information, edit to `open` with `--body "new information"`. That replaces the
current body; previous bodies remain in audit snapshots. Only staff should use
`resolved` or `closed` after verifying the outcome.

## 14. Test before spending money on AWS

```bash
python -m unittest discover -s tests -v
```

Expected: **13 tests, OK**. Tests cover previews, duplicate writes, stale versions,
review routing, grounding checks, priorities, schema restrictions, human reopening,
failures, the real local MCP round trip and the real LangChain tool loop using a
scripted model. They require no OpenAI key.

A scripted model validates plumbing, not GPT-4o mini's quality. The live call in
Step 3 and live ticket preview in Step 11 are separate checks you perform with
your own account. These live calls and AWS deployment were not executed while
preparing this tutorial.

## 15. Choose a small AWS deployment

Use **Amazon Lightsail, Ubuntu 24.04 LTS, public IPv4, 2 GB RAM**, in a region you
choose (Mumbai is a reasonable location to inspect for India-based learners).
The 2 GB general-purpose plan is listed at **US$12/month**; the 1 GB plan is
US$7/month. Prices are before taxes, extra usage and optional services. [4]

VS Code documents 1 GB as its remote-host minimum and recommends at least 2 GB with two cores. [7]
Our recommendation is the 2 GB plan for this tutorial because VS Code Remote SSH,
Python and the server share memory. The 1 GB plan is a smaller worker-only option
if you validate memory usage and disconnect VS Code when finished. The 0.5 GB
plan is too constrained for the intended teaching workflow. This sizing judgement
is not a measured capacity guarantee; check `free -h` and actual workload.

Lightsail gives us a small virtual Linux computer with bundled disk and networking.
We use one machine, one worker and SQLite. There is no load balancer, managed
database, NAT gateway, container cluster or GPU to configure in this path.

**AWS hosts the application; OpenAI hosts the model.** Charges are separate.
A cloud deployment here means a private background service, not a public website.
Remote MCP over HTTP is a later extension; it is not required when both processes
run on the same AWS machine.

## 16. Create the Lightsail instance

In your AWS account:

1. Open **Lightsail** and choose **Create instance**.
2. Select a region and a Linux/Unix, **OS Only → Ubuntu 24.04 LTS** blueprint.
3. Choose the general-purpose **2 GB, public IPv4** bundle. Confirm the displayed
   regional price. Do not assume a trial or account credit is available.
4. Name it `ticket-agent-lab` and create it. Creating the instance starts billable
   resources in your account.
5. Wait for the instance to become running. Record its public IPv4 address.
6. In Lightsail networking, create and attach a **static IP** to keep the address
   stable. An unattached static IP can incur charges; review billing. [5]
7. In the instance firewall, allow **SSH TCP 22 only from your current public IP**.
   Enable the console's browser-SSH allowance if you plan to use it. Remove
   unnecessary default HTTP rules. Review IPv6 rules too, or disable IPv6 for this
   lab if unused. Do not open 8000, 80 or 443 for this stdio application. [6]

If your home/office public IP changes, update the SSH rule. The laptop's local
address (for example 192.168.x.x) is not the public source address AWS sees.

Create an AWS billing budget/alert appropriate for the lab, for example US$15/month
if using only the US$12 instance. Alerts are not a guaranteed hard spending cap.
The alert value is a planning choice, not an AWS requirement.

## 17. Connect from VS Code using SSH

Download the default SSH private key for the instance's AWS region from Lightsail
account SSH-key settings, or use the key pair you selected at instance creation.
Store it in your local `.ssh` directory; never add it to the project archive.
On macOS/Linux restrict permissions:

```bash
chmod 600 ~/.ssh/LightsailDefaultKey.pem
```

On Windows keep the file accessible only to your Windows user; if OpenSSH reports
an unprotected-key error, correct its file ACL using Windows file security settings.

Open VS Code's Command Palette → **Remote-SSH: Open SSH Configuration File**.
Add this entry to your user SSH config, replacing both placeholders:

```sshconfig
Host ticket-agent-aws
    HostName YOUR_LIGHTSAIL_STATIC_IP
    User ubuntu
    IdentityFile /absolute/path/to/your/LightsailDefaultKey.pem
    IdentitiesOnly yes
```

On Windows the IdentityFile can be `C:/Users/YourName/.ssh/LightsailDefaultKey.pem`.
It must be a path on your laptop, not on AWS. Test in a **local** terminal:

```bash
ssh ticket-agent-aws
```

Verify the host-key fingerprint against the instance before accepting it on first
connection. You can inspect host public-key fingerprints through the trusted
Lightsail browser SSH session with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`.
Type `exit` after the test.

In VS Code choose **Remote-SSH: Connect to Host → ticket-agent-aws**. Select Linux
if asked. The new window should show `SSH: ticket-agent-aws` in its status bar.
Remote SSH runs editor support and terminals on the server. [7]

**Important:** from this point, distinguish LOCAL terminal (laptop) from REMOTE
terminal (AWS). `hostname` in a remote terminal shows the AWS machine.

## 18. Prepare Ubuntu and transfer the source

In the **REMOTE** terminal:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip unzip
python3 --version
mkdir -p /home/ubuntu/ticket-agent
```

`sudo` runs administrative setup; `apt` installs OS packages. Application commands
later run as the normal `ubuntu` user. No AWS access keys are needed inside the app.

Back in a **LOCAL** terminal, from the extracted `ticket-agent` project root, make
a clean deployment ZIP with the included helper:

```bash
python deploy/package_source.py
scp ticket-agent-source.zip ticket-agent-aws:/home/ubuntu/ticket-agent-source.zip
```

The helper includes only named source/configuration-template directories/files.
It excludes `.env`, your database, backups, `.venv` and keys. Do not copy the whole
local virtual environment to Linux; create a fresh one on AWS.

In the **REMOTE** terminal:

```bash
unzip /home/ubuntu/ticket-agent-source.zip -d /home/ubuntu/ticket-agent
cd /home/ubuntu/ticket-agent
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
```

Use **File → Open Folder → /home/ubuntu/ticket-agent** in the remote VS Code window.
Install the Python extension in the SSH target if prompted; select
`/home/ubuntu/ticket-agent/.venv/bin/python` as its interpreter.

## 19. Configure and verify the AWS copy

In the **REMOTE** terminal:

```bash
cd /home/ubuntu/ticket-agent
cp .env.example .env
chmod 600 .env
```

Edit the remote `.env` through VS Code:

```dotenv
OPENAI_API_KEY=your_actual_key_here
OPENAI_MODEL=gpt-4o-mini
TICKET_DB=/home/ubuntu/ticket-agent/data/tickets.db
```

The absolute database path avoids accidentally creating a second database when
commands run from different directories. For this single-user lab the key is a
restricted local file. For multi-user production use a dedicated service account
and managed secrets. Do not paste the key into shell commands that retain history.

```bash
mkdir -p data
chmod 700 data
.venv/bin/python lessons/01_check_model.py
.venv/bin/ticket-agent init
.venv/bin/ticket-agent seed
.venv/bin/ticket-agent run --id 1
.venv/bin/ticket-agent run --id 1 --apply
.venv/bin/ticket-agent show 1
```

This starts a **new cloud demo database**, separate from your laptop database.
No earlier tickets have been migrated. Confirm preview then update before starting
a permanent worker. The same code now operates on AWS.

## 20. Keep the worker running after VS Code closes

Linux **systemd** can start a program on boot, monitor it and restart it after a
process failure. The included `deploy/ticket-agent.service` defines our service.
It runs as `ubuntu`, sets the project working directory, reads `.env`, and starts:

```bash
ticket-agent watch --apply --interval 300 --limit 5
```

In the **REMOTE** terminal:

```bash
sudo cp deploy/ticket-agent.service /etc/systemd/system/ticket-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now ticket-agent
sudo systemctl status ticket-agent --no-pager
sudo journalctl -u ticket-agent -n 50 --no-pager
```

`daemon-reload` reads the unit file. `enable` starts it at future boots. `--now`
starts it immediately. Expect `active (running)`. This proves the process is alive,
not that every model call succeeds; inspect logs and ticket outcomes too.

Add a ticket from the remote terminal:

```bash
.venv/bin/ticket-agent add --subject "Login failure" --body "My password reset email has not arrived."
```

Record its ID, wait up to a polling interval plus processing time, then run
`.venv/bin/ticket-agent show ID` and `.venv/bin/ticket-agent audit ID`.
**Checkpoint:** a persisted update and audit entry prove the deployed path worked.
You can now close VS Code; systemd keeps the worker running.

Useful commands:

```bash
sudo journalctl -u ticket-agent -f
sudo systemctl restart ticket-agent
sudo systemctl stop ticket-agent
sudo systemctl start ticket-agent
```

Ctrl+C stops the live log display, not the service. `systemctl stop` stops the
worker. Avoid running another `watch` while systemd is active: version guards
prevent stale writes, but concurrent workers can waste duplicate model calls.

For source updates: stop the service, copy the changed source, rerun tests, then
start it. Back up data first. Do not overwrite `.env` or `data/` when updating.

## 21. Cost planning and small-usage settings

Reference prices checked 31 October 2026; verify them in the linked official
pages and your selected region/account before creating resources.

| Item | Planning value |
|---|---|
| Lightsail Linux public-IPv4 2 GB | US$12/month bundle |
| Smaller 1 GB option | US$7/month bundle; validate memory |
| GPT-4o mini standard text input | US$0.15 per million input tokens |
| GPT-4o mini standard text output | US$0.60 per million output tokens |
| Other possible costs | Taxes, snapshots, excess transfer, detached static IPs |

Illustrative API calculation, not measured usage: assume **3,000 total input tokens
and 600 total output tokens per ticket across all agent calls**.

- Input: 3,000 / 1,000,000 × $0.15 = $0.00045.
- Output: 600 / 1,000,000 × $0.60 = $0.00036.
- Total: **$0.00081/ticket**, or **$0.81 for 1,000 tickets**.

Combined illustration: $12 instance + $0.81 API = **$12.81/month before other
charges**. Real usage depends on prompts, tool rounds, retries and ticket lengths;
previewing and then applying calls the model twice. Do not equate tickets with
API requests. [1,4]

For early practice, process one ticket at a time, inspect API usage, then enable
five-ticket batches at five-minute intervals. Stop the worker when experimenting
with broken credentials or persistent failures. Failed tickets remain eligible
and retry each polling cycle; this reference has no durable retry counter or
spending circuit breaker. Add bounded attempts/backoff and a dead-letter queue
before operating unattended on important customer traffic.

## 22. Back up and clean up

To make a consistent database backup, from the remote project root:

```bash
.venv/bin/python deploy/backup_db.py
```

The helper uses SQLite's backup API, which is safer than copying a live database
file during writes. It prints the backup path. Copy that exact file off the
instance using `scp` in your **LOCAL** terminal. Example (replace filename):

```bash
scp ticket-agent-aws:/home/ubuntu/ticket-agent/data/backups/ACTUAL_BACKUP_NAME.db .
```

A backup stored only on the same instance does not protect against instance loss.
For a lab restore, stop the worker, preserve the current database separately, copy
the backup to the configured database path, inspect it, then restart. Restoring an
old snapshot can make old tickets eligible again; audit the restored state first.

When finished with the AWS lab:

1. Stop the service: `sudo systemctl disable --now ticket-agent`.
2. Download source changes and any data/backups you want to keep.
3. Delete the Lightsail instance when you no longer need it. Stopping an instance
   alone does not end its instance charges. [5]
4. Release unused static IPs and delete unwanted snapshots/disks separately.
5. Review the AWS billing page and OpenAI usage dashboard.
6. Revoke a disposable API key if it was created only for this exercise.

Deletion removes the server and its local data. Back up first.

## 23. Troubleshooting by symptom

| Symptom | Check and correction |
|---|---|
| `python` not found | Use `py -3.12` on Windows or `python3.12` on macOS/Linux for environment creation |
| ModuleNotFoundError | Activate correct `.venv`, select its interpreter and install requirements |
| `ticket-agent` not found | Run editable install; use `.venv/bin/ticket-agent` on Linux or the Windows Scripts path |
| Tiny server appears frozen | It is waiting for MCP; run the client, which launches the server |
| MCP connection closes | Remove stdout prints; verify interpreter, module path and server stderr |
| API 401 / AuthenticationError | Verify `.env` key, current folder and project access; never print the key |
| API 429 | Inspect quota and rate limits, stop polling, then retry after correcting the cause |
| Model not found | Verify GPT-4o mini access; its deprecated status may require an explicit model change |
| CLI says only `error_type` | Run the model-check lesson first; use the debugger locally for detailed exceptions |
| Empty batch `[]` | No eligible open, unprocessed tickets; add a new ticket or inspect review status |
| Version conflict | Someone edited the ticket; reread and analyse current revision |
| No `data/tickets.db` where expected | Inspect `TICKET_DB` and working directory; use absolute path on AWS |
| SSH timeout | Instance running? Correct static IP? Port 22 allows your current public IP? |
| Permission denied (publickey) | Correct region key, Ubuntu username, key path and local key permissions? |
| VS Code remote is slow or killed | Check `free -h`; use 2 GB plan and avoid multiple remote sessions |
| systemd status=203/EXEC | Check exact `.venv/bin/ticket-agent` path and executable installation |
| Service runs but no updates | Inspect logs, API access, eligible tickets and database path |
| Service exits repeatedly | Stop it; check `.env`, paths, permissions, dependencies and logs before restarting |
| Local preview works, cloud fails | Recheck cloud key, outbound connectivity and remote interpreter |

## 24. Suggested teaching plan and exercises

| Session | Build | Learner checkpoint |
|---|---|---|
| 1 — 90 minutes | Environment, model call, tiny MCP server/client | Explain which process executes a tool |
| 2 — 90 minutes | SQLite, schema, MCP tools, LangChain loop | Produce a preview and inspect fields |
| 3 — 90 minutes | Updates, review, tests, debugging | Explain stale-version and duplicate protection |
| 4 — 90 minutes | Lightsail, Remote SSH, systemd, costs | Add a cloud ticket and verify persisted update |

Exercises:

1. Add ten fictional tickets with your own expected category and priority. Compare
   model output to your labels. Record urgent misses, not just overall accuracy.
2. Add a verified knowledge article and check when keyword search returns it.
3. Lower the confidence on a test Analysis object and observe review routing.
4. Simulate a human edit between snapshot and update; explain why rejection matters.
5. Stop and restart the service; verify processed tickets are not updated again.
6. Calculate costs from actual API token usage, including multiple agent turns.

## 25. What this tutorial does and does not deploy

You finish with a functioning single-machine agent worker and local ticket store,
managed from VS Code. It analyses, routes and updates internal records. Customer
replies remain drafts. It does not reset passwords, issue refunds or send messages.

Connecting Zendesk/Freshdesk/Jira/ServiceNow requires a provider adapter behind
MCP: authenticated ticket reads, guarded updates, internal-note mapping, provider
rate limits and durable idempotency. A remote API mutation and a local SQLite
write cannot use the same transaction; use an outbox/reconciliation design.

A public UI, webhook intake, remote MCP HTTP authentication, multi-user permissions,
secret manager, calibrated classifier, attachment handling and production monitoring
are further work. Do not expose this stdio service on the internet by simply
switching transports. The local OS user is trusted in this lab.

## Official references

[1] OpenAI GPT-4o mini model, features and pricing:
https://developers.openai.com/api/docs/models/gpt-4o-mini

[2] MCP Python SDK 1.x documentation:
https://py.sdk.modelcontextprotocol.io/v1/

[3] LangChain agents and structured output:
https://reference.langchain.com/python/langchain/agents/factory/create_agent
https://docs.langchain.com/oss/python/langchain/structured-output

[4] AWS Lightsail bundles:
https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html

[5] AWS Lightsail billing and account management:
https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-frequently-asked-questions-faq-billing-and-account-management.html

[6] AWS Lightsail firewalls:
https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-editing-firewall-rules.html

[7] VS Code Remote SSH:
https://code.visualstudio.com/docs/remote/ssh
