# Architecture (C4)

Structurizr DSL source: [`workspace.dsl`](workspace.dsl).

Validated and exported via Structurizr (`SystemContext`, `Containers`, `Components`).

## Level 1 — System Context

```mermaid
graph LR
  Operator["Operator"] -->|Runs apply / worker| CU["apply-agents"]
  CU -->|Computer-use agent turns| OpenAI["OpenAI API"]
  CU -->|Claim jobs, report steps, poll OTP| Landed["Landed API"]
  CU -->|Browse and submit applications| ATS["Job Boards / ATS"]
  CU -->|Solve Turnstile / reCAPTCHA| NopeCHA["NopeCHA"]
  CU -->|Solve hCaptcha| NoneCap["NoneCap"]
```

**apply-agents** is a local Camoufox + OpenAI computer-use applier. It either applies to one URL from config or claims jobs from Landed’s worker API. There is no in-repo HTTP server or DB — persistence is local JSON + browser profile.

## Level 2 — Containers

```mermaid
graph TB
  Operator["Operator"]
  subgraph CU["apply-agents"]
    ApplyCLI["Apply CLI"]
    WorkerCLI["Worker CLI"]
    Harness["Browser Harness"]
    Files["Local File Store"]
  end
  OpenAI["OpenAI API"]
  Landed["Landed API"]
  ATS["Job Boards / ATS"]
  NopeCHA["NopeCHA"]
  NoneCap["NoneCap"]

  Operator -->|manual apply / --login| ApplyCLI
  Operator -->|claim loop| WorkerCLI
  Operator -->|edits configs / form KB| Files
  ApplyCLI -->|run_local_apply| Harness
  WorkerCLI -->|run_local_apply + callbacks| Harness
  WorkerCLI -->|claim + finish| Landed
  Harness --> Files
  Harness --> OpenAI
  Harness --> ATS
  Harness --> NopeCHA
  Harness --> NoneCap
  Harness -->|steps, artifacts, OTP| Landed
```

| Container | Role | Entry |
|---|---|---|
| Apply CLI | Single-job apply, login, NopeCHA cache | `job-apply` / `python -m computer_use.apply` |
| Worker CLI | Poll Landed, claim, apply, finish | `job-worker` / `python -m computer_use.worker` |
| Browser Harness | Camoufox + agent loop + features + captcha | `browser/local.py` |
| Local File Store | Configs, KB, learnings, costs, profile, resumes | repo root / `.cache` / `.camoufox-profile` |

## Level 3 — Components (Browser Harness)

```mermaid
graph TB
  subgraph Harness["Browser Harness"]
    Config["Apply / Worker Config"]
    Registry["Feature Registry"]
    FormKB["Form Knowledge"]
    Learnings["Learnings"]
    Signup["Account Signup"]
    OTP["Verification Code"]
    Prompts["Apply Prompts"]
    Agent["Agent Runner"]
    Camoufox["LocalCamoufoxComputer"]
    Captcha["Captcha Solvers"]
    LandedClient["Landed Client"]
    Escape["Aggregator Escape"]
    Costs["Cost Tracker"]
    FillLog["Fill / Agent Log"]
  end

  Registry --> FormKB
  Registry --> Learnings
  Registry --> Signup
  Registry --> OTP
  Registry --> Prompts
  Agent --> Prompts
  Agent --> Registry
  Agent --> Camoufox
  Agent -->|turns| OpenAI["OpenAI API"]
  Camoufox --> Captcha
  Camoufox --> Escape
  Camoufox -->|browse/fill| ATS["Job Boards / ATS"]
  Captcha --> NopeCHA["NopeCHA"]
  Captcha --> NoneCap["NoneCap"]
  OTP --> LandedClient
  Escape --> LandedClient
  FillLog --> LandedClient
  LandedClient -->|HTTP| Landed["Landed API"]
```

## Files

| File | Description |
|---|---|
| [`workspace.dsl`](workspace.dsl) | Structurizr workspace (source of truth) |
| [`SystemContext.mmd`](SystemContext.mmd) | Exported Mermaid (styled) |
| [`Containers.mmd`](Containers.mmd) | Exported Mermaid (styled) |
| [`Components.mmd`](Components.mmd) | Exported Mermaid (styled) |

To re-export from Structurizr Lite / CLI, open `workspace.dsl` and export views `SystemContext`, `Containers`, and `Components`.
