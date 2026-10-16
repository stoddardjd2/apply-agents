# apply-agents

Apply to a **specific job URL** with your **resume PDF**, using local headed [Camoufox](https://camoufox.com/) + OpenAI Agents computer use.

MIT licensed — see [LICENSE](LICENSE).

## Configure

Copy the example configs (do not commit your filled copies — they are gitignored):

```powershell
copy apply.config.example.json apply.config.json
copy worker.config.example.json worker.config.json
```

Edit `apply.config.json`:

```json
{
  "job_url": "https://your-board.com/jobs/123",
  "resume_path": "resumes/resume.pdf",
  "submit": false,
  "profile": { "first_name": "Your", "email": "", "...": "..." }
}
```

Put your PDF at `resume_path`. Fill `profile.email` / `profile.phone` (or set `APPLICANT_EMAIL` / `APPLICANT_PHONE` in `.env`). The agent uses `profile` for common application fields (name, links, work auth, EEO preferences, custom answers, etc.).

**Salary / compensation:** leave `profile.salary_expectation_usd` as `null` to auto-pick an annual USD figure from the job’s posted salary range (Landed claim/DB) biased by `years_experience`. Set it to a number (e.g. `120000`) to **override** that auto value for every apply.

Unknown screening questions are recorded in `form_knowledge.json` (override with `FORM_KNOWLEDGE_PATH`). The agent answers from `profile` and prior KB answers first; only gaps become pending. Set each pending entry’s `answer` field to reuse it on later applies, or set `"ai_may_answer": true` to let the agent write a short answer for that question.

`account_signup` lets the agent create an employer-site account on **non-major** companies (email in config; set `APPLY_ACCOUNT_PASSWORD` in `.env`). Major employers are skipped; Google SSO is preferred when available.

## Setup

```powershell
cd path\to\apply-agents
.\.venv\Scripts\Activate.ps1
pip install -e ".[local]"
```

This project uses its own Camoufox install under `.cache/camoufox-install` (see `CAMOUFOX_INSTALL_DIR` in `.env`) so it can run at the same time as another Camoufox on this PC that uses `%LOCALAPPDATA%\camoufox`. The first apply/login run downloads the browser into that folder (~300MB). Profiles stay separate via `BROWSER_PROFILE=.camoufox-profile`.

One-time browser login (Cloudflare / Google):

```powershell
python -m computer_use.apply --login
```

Captcha solvers (agent never clicks puzzles) — full list, env vars, and links:

→ **[src/computer_use/captcha/README.md](src/computer_use/captcha/README.md)**

Quick setup:

```powershell
# NoneCap key for hCaptcha → https://dashboard.nonecap.com  (NONECAP_KEY in .env)
# NopeCHA addon for Turnstile / reCAPTCHA / etc.:
python -m computer_use.apply --ensure-nopecha
```

## Run (manual / testing)

Still works for a single URL + resume from `apply.config.json`:

```powershell
python -m computer_use.apply
python -m computer_use.apply --job-url https://... --resume resumes\me.pdf
python -m computer_use.apply --submit
```

Or set `"submit": true` in `apply.config.json` / `SUBMIT_APPLICATION=1` in `.env`.

When the site opens a file picker, the harness auto-attaches your PDF.

## Landed worker queue

Claims ready applications from Landed’s API, uses `apply.config.json` for profile/signup, and Landed’s tailored resume + cover letter per job.

API URL defaults to `http://localhost:8180`. Worker token is read from `../landed/.env` (`LANDED_WORKER_TOKEN`) — no need to duplicate it here.

1. Edit `worker.config.json` — one `blocklist` (e.g. `linkedin`, `workday`) blocks both adapter and URL host
2. Stop Landed’s Node browser-worker so only this process claims jobs
3. Run:

```powershell
python -m computer_use.worker
python -m computer_use.worker --once
```

## Costs

Estimates append to `costs.json`.
