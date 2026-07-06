# Dispatcher MCP Server — Stress Test Report

_Tested 2026-07-06. Target: `src/mcp_servers/dispatcher/`. Tester: Claude (Opus 4.8)._

The dispatcher exposes three MCP tools (`submit_job`, `get_job_status`,
`update_job_status`) backed by an SQLite job table. `submit_job` persists a job as
`Running` and **spawns a real `agy` background agent** via `subprocess.Popen` to work it.

## How it was tested

- **Baseline unit suite** — `uv run pytest tests/dispatcher/ --cov`.
- **Code-layer stress** — harness against `tools/jobs` with `Popen` mocked and a throwaway
  DB (no real agents spawned): volume, concurrency, adversarial payloads, connection leaks.
- **Live MCP tools** — the registered server, in-process: validation boundaries, not-found
  paths, and **one** controlled end-to-end submit (real `agy` worker, terminated after
  observation).

## Results

| Test | Result | Notes |
|------|--------|-------|
| Baseline unit suite | ✅ PASS | 15 passed, **100%** line coverage |
| Volume — 1000 submits | ✅ PASS | 1000 unique UUIDs, all persisted, ~1000 submit/s (mocked) |
| Concurrency — 300 submits / 32 threads | ✅ PASS | no SQLite lock errors |
| Concurrency — 200 racing updates, same job | ✅ PASS | no errors, deterministic terminal state |
| Large payload — 5 MB | ✅ PASS | exact round-trip |
| Deeply nested payload — 500 levels | ✅ PASS | stored & read |
| Unicode / emoji / NUL / control chars | ✅ PASS | exact round-trip (JSON-escaped) |
| SQL-injection strings in payload | ✅ PASS | parameterized queries; table intact |
| Empty payload `{}` | ✅ PASS | accepted |
| Protocol validation — bad UUID | ✅ PASS | rejected by pattern before DB |
| Protocol validation — injection in `worker_type` | ✅ PASS | rejected before spawn |
| Not-found — get & update on unknown UUID | ✅ PASS | clean `{"error": ...}` |
| Live E2E — submit → get → update → get | ✅ PASS | timestamps advance correctly |
| **Connection leak** | ❌ **FAIL** | see B1 |

## Fix status

| ID | Issue | Status |
|----|-------|--------|
| B1 | Connection leak | ✅ **Fixed** — `contextlib.closing` on every connection; regression test asserts each opened connection is closed |
| R3 | No lifecycle state machine | ✅ **Fixed** — terminal (`Completed`/`Failed`) status is now immutable |
| R4 | No size bounds | ✅ **Fixed** — `worker_type` `max_length=256`; payload capped at 1 MiB |
| B2 | Live DB written into the git clone | ⬜ **Follow-up (deploy)** — not fixable in this repo; see below |
| R1 | No spawn rate limit / concurrency cap | ⬜ Follow-up — interacts with R2, see below |
| R2 | Spawned workers can't report back | ⬜ Follow-up — needs worker MCP/creds check |
| R5 | No list/cleanup path | ⬜ Follow-up — new tool |
| R6 | No authorization | ⬜ Accepted risk (local single-user) |

## Bugs found

### B1 — SQLite connections are never closed (leak) 🔴 — FIXED
`with sqlite3.connect(...)` commits/rolls back on exit but **does not close** the
connection (Python gotcha). Stress harness saw **350 unclosed-DB `ResourceWarning`s across
150 operations** (~2.3 leaked handles/op). Under sustained load this exhausts file
descriptors.
- **Where:** every `sqlite3.connect` in `tools/jobs.py` (`_init_db`, `submit_job`,
  `_fetch_job`, `update_job_status`).
- **Fix:** use `contextlib.closing(sqlite3.connect(...))`, or `conn = ...; try/finally:
  conn.close()`. The `with` block alone is not enough.

### B2 — Live DB is written into the git clone, un-ignored 🔴
The deployed server runs with `MCP_DISPATCHER_DB_PATH=/home/deck/.config/agents/dispatcher.db`
— the agent-config git clone. This is **exactly** the location `get_db_path`'s own comment
warns against ("risks being committed or clobbered on re-clone"). Confirmed live: the file
shows as untracked (`?? dispatcher.db`) and is **not** gitignored, so it will be committed or
wiped on re-clone.
- **Fix (deploy):** point `MCP_DISPATCHER_DB_PATH` at `~/.mcp/dispatcher.db` (the code
  default) in the `ansible-ai-agents` MCP registration, **and/or** add `dispatcher.db` to the
  agent-config `.gitignore` as a backstop.

## Risks / hardening gaps (not crashes, but worth an issue)

- **R1 — No rate limit or concurrency cap on `submit_job`.** Each submit spawns a real `agy`
  agent unconditionally. `submit_job` × N launches N background AI agents — a resource/cost
  DoS with a single loop. Consider a max-in-flight cap (count `Running` jobs) and/or a
  per-interval limit. **Held off intentionally:** a cap keyed on the `Running` count would
  deadlock while R2 is unfixed (jobs never leave `Running`), so fix R2 first or make the cap
  time-based.
- **R2 — Spawned workers can't report back → jobs stick in `Running`.** The spawn env
  whitelist passes only `PATH/USER/HOME/LANG/LC_ALL` (+ AGY/DB vars). The live probe worker
  ran but never updated its status; it likely lacks the dispatcher MCP registration and/or
  API credentials in its stripped env. Verify the worker actually has the tools/creds the
  prompt tells it to use, or jobs are write-only from the worker's side.
- **R3 — No lifecycle state machine.** `Completed → Running` (and any other transition) is
  allowed. Terminal states should probably be immutable.
- **R4 — No size/length bounds.** `worker_type` accepts 100k chars; payloads accept ≥5 MB.
  No `maxLength` / payload-byte cap → unbounded row size.
- **R5 — No list/cleanup path & unbounded growth.** No tool lists jobs or prunes terminal
  ones; the table grows forever. (Also limits observability — there's no way to see stuck
  `Running` jobs.)
- **R6 — No authorization.** Any caller can read or mutate any job given its UUID. Low risk
  for a local single-user server; note it before this is ever exposed more widely.

## Suggested priority

1. **B1** (fd leak) and **B2** (DB-in-git) — fix before any real use.
2. **R1** (spawn cap) and **R2** (worker can't report back) — the server's core purpose is
   dispatching workers that finish; today they may run unbounded and never close the loop.
3. **R3–R6** — hardening once the above are solid.

## Test artifacts / cleanup

- Stress harness: `scratchpad/stress.py` (session scratchpad, `Popen` mocked).
- Live probe job `a2b610d6-…` was submitted, its `agy` worker (PID 10206) terminated, and the
  job marked `Completed`. **Left in place for you to decide:** the untracked
  `~/.config/agents/dispatcher.db` (evidence of B2) and an empty `~/.mcp/dispatcher.db`.
