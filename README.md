# computer-use-openai

OpenAI Agents API [computer use](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use) project with a hosted-browser end-to-end test for Indeed Easy Apply / Quick Apply.

The browser runs in OpenAI's hosted environment. This repo:

1. Creates an Agents API session with `{ "type": "computer_use" }`
2. Auto-approves configured Indeed origins
3. Supplies Indeed sign-in credentials from env (or prompts interactively)
4. Runs a Quick Apply flow and reports the result

## Setup

```powershell
cd C:\Users\jared\programming\computer-vision-openai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Fill `.env`:

- `OPENAI_API_KEY`
- `INDEED_EMAIL` / `INDEED_PASSWORD`
- Optional: `INDEED_QUERY`, `INDEED_LOCATION`, `INDEED_JOB_URL`

## Run Indeed Quick Apply

Dry run (fills the form, stops before final submit — default):

```powershell
python -m computer_use.indeed_apply
```

Full submit:

```powershell
$env:SUBMIT_APPLICATION="1"
python -m computer_use.indeed_apply --submit
```

Or target a specific listing:

```powershell
python -m computer_use.indeed_apply --job-url "https://www.indeed.com/viewjob?jk=..."
```

Artifacts land in `artifacts/` (`last-screenshot.jpg`, `result.txt`).

## Tests

Unit tests (no API key):

```powershell
pytest -q
```

Live e2e (uses OpenAI + Indeed):

```powershell
$env:RUN_INDEED_E2E="1"
$env:SUBMIT_APPLICATION="0"
pytest -q tests/test_indeed_quick_apply.py -k e2e
```

## Notes

- Origin access must be approved per [the computer-use guide](https://developers.openai.com/api/docs/guides/agents-api/tools/computer-use). `AUTO_APPROVE_ORIGINS` covers common Indeed hosts.
- Sign-in values are sent only through `computer_use_approval_request_result` events, never in chat.
- Keep `SUBMIT_APPLICATION=0` until you are ready to send a real application.
