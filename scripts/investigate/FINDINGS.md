# Investigation: intermittent `Error getting response`

Date: 2026-10-15  
Scripts: this directory only (no production code changes).

## Symptom (worker terminal)

```
Opening headed Camoufox (live window)...
Max agent turns: 80
NopeCHA captcha solver loaded: ...
Error getting response
Finished …: failed_retryable → failed_permanent / system.retry_exhausted
```

Sometimes the same Glassdoor job proceeds (tab switch → agent steps). So intermittent.

## ROOT CAUSE (confirmed)

**Stale async OpenAI/httpx client across `asyncio.run()` calls.**

Worker pattern in [`src/computer_use/worker.py`](../../src/computer_use/worker.py):

```python
while True:
    ...
    asyncio.run(_run_one(...))  # new event loop every job
```

After job 1, the Agents SDK / OpenAI async client keeps httpx connections bound to the **closed** loop. Job 2’s first `responses.create` dies with:

```
RuntimeError: Event loop is closed
```

which the SDK logs only as `Error getting response`.

### Reproduction

| Script | Result |
|---|---|
| `run_apply_like.py --attempts 2 --job-url <glassdoor>` | Attempt 1 OK; attempt 2 → `Error getting response` + `RuntimeError: Event loop is closed` |
| `probe_event_loop_reuse.py` (example.com, same process, two `asyncio.run`) | Run A exit=0; Run B EXC `Event loop is closed` |

This matches “sometimes works” (first job after worker start) vs “insta fail” (later jobs in the same process).

## What `Error getting response` actually is

From `openai-agents` (`agents/models/openai_responses.py`): any exception from `client.responses.create` is logged as the short string **`Error getting response`**, then re-raised. The real message is on the exception (often `openai.BadRequestError`).

Production currently does **not** print that exception before finishing the Landed job (logging changes from earlier were not present in `local.py` / `worker.py` when checked).

## Probes run

| Script | Result |
|---|---|
| `probe_api_image_errors.py` | Invalid `image_url` → `BadRequestError` 400 with `input[].output.image_url` (same class of failure the SDK wraps) |
| `probe_screenshot_race.py` | 28/28 screenshots valid on Glassdoor (concurrent bursts, reload, new tab) |
| `probe_first_response.py` | 10/10 first Responses calls OK; payload is `[{'type': 'computer'}]`, `use_preview=False` for `gpt-6-luna` + `tool_choice=auto` |
| `probe_two_turn_loop.py` | 6/6 OK: first call → Camoufox screenshot → `computer_call_output` second call |
| `probe_insta_fail.py` (full apply prompt, 5×) | **Never** hit `Error getting response`; only `MaxTurnsExceeded` (max_turns=4). First model turns + screenshots succeeded every time |
| `probe_profile_contention.py` | Two Camoufox on same `.camoufox-profile` concurrently → **both fail to launch** |

## Captcha notes from real apply mimic (Glassdoor → iCIMS)

From `run_apply_like.py` attempt 1 (full `computer_use.apply` path):

- Harness armed **NopeCHA for RECAPTCHA** and waited 90s → **did not clear**.
- Agent report said **hCaptcha** and that it never cleared.
- **NoneCap never ran** (no `NoneCap: solving…` log) — detection/arming treated it as RECAPTCHA, not HCAPTCHA.

So solvers are loaded, but on this ORAU/iCIMS gate the wrong solver path was chosen / NopeCHA failed.

## Earlier probes (still valid)

| Script | Result |
|---|---|
| `probe_api_image_errors.py` | Invalid `image_url` → `BadRequestError` 400 (also wraps as `Error getting response`) |
| `probe_screenshot_race.py` | 28/28 screenshots valid |
| `probe_first_response.py` | 10/10 first calls OK with `[{type: computer}]` |
| `probe_two_turn_loop.py` | 6/6 OK (single `asyncio.run` each process / one loop) |
| `probe_profile_contention.py` | Two Camoufox on same profile → launch fails (separate issue) |

Single-loop probes looked “healthy” because they never did the worker’s **second** `asyncio.run`.

## Fix (applied)

[`src/computer_use/worker.py`](../../src/computer_use/worker.py): one `asyncio.run(_run_forever_async(...))` for the whole worker; jobs are `await _run_one(...)` on that loop. Sync Landed claim uses `asyncio.to_thread`.

Verified with `probe_event_loop_reuse.py`: fixed pattern A+B both exit 0.
