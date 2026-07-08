# dispatcher

Asynchronous agent-to-agent task delegation and orchestration: agents spawn background subagents
for long-running workflows, with job state tracked in an SQLite database.

Installed as `mcp-dispatcher`; registered as `dispatcher`.

## Tools

### `submit_job`
Log a new job as `Running` and asynchronously spawn a detached background `agy` process for the
given worker type. The worker fetches its own payload from the database via `get_job_status`.
Returns the new job's UUID.

**Arguments**:
- `worker_type` (string, required): Subagent worker type to spawn (e.g. `swarm_qa`, `swarm_devlead`). Alphanumeric, dashes, and underscores only.
- `payload` (object, required): JSON-serializable task instructions, context, or data for the worker.

### `get_job_status`
Retrieve one job's status and original payload.

**Arguments**:
- `job_id` (string, required): The UUID of the job to fetch.

Returns a JSON object with the job's `id`, `status`, `worker_type`, `payload`, and
`created_at` / `updated_at` timestamps.

### `update_job_status`
Set a job's `status` and stamp `updated_at` — the path a spawned worker uses to report progress.
The status is validated against the `JobStatus` enum, and terminal states are immutable.

**Arguments**:
- `job_id` (string, required): The UUID of the job to update.
- `status` (string, required): One of `Running`, `Completed`, or `Failed`.

Returns the updated job object, or an `error` if no job matches the id.

### `list_jobs`
List jobs, newest first.

**Arguments**:
- `status` (string, optional): Filter to a single `JobStatus` (`Running`, `Completed`, `Failed`).
- `limit` (integer, optional): Maximum jobs to return (default `50`, range 1–500).

### `cleanup_jobs`
Delete terminal (`Completed` / `Failed`) jobs.

**Arguments**:
- `older_than_days` (integer, optional): Only delete terminal jobs whose last update is older than this many days. Omit to delete all terminal jobs.

## Job lifecycle

Statuses come from a fixed `JobStatus` enum: **`Running`** (set when `submit_job` spawns the
worker), **`Completed`** (worker finished), and **`Failed`** (spawn failed, or the worker reported
failure). Each row also carries `created_at` and `updated_at` (UTC ISO-8601). Terminal states
(`Completed`, `Failed`) cannot be changed once set.

## Configuration

- `MCP_DISPATCHER_ALLOW_SPAWN` (required): Must be `"true"` or `"1"` to allow `submit_job` to spawn background processes. If unset or false, `submit_job` raises a runtime error — a safety guard against accidental spawning.
- `MCP_DISPATCHER_DB_PATH`: SQLite database path (default `~/.mcp/dispatcher.db`, alongside the github server's `audit.db`).
- `MCP_DISPATCHER_MAX_RUNNING`: Maximum concurrently-`Running` jobs before `submit_job` is refused (default `16`).

## Usage patterns

- **Long-running orchestration** — the master agent splits a project into discrete tasks, calls `submit_job` for each, and polls with `get_job_status` or `list_jobs`.
- **Background workers** — the spawned `agy` process boots with `AGY_JOB_ID` set, reads its payload via `get_job_status`, does the work, and calls `update_job_status` to mark the job `Completed` or `Failed`.
