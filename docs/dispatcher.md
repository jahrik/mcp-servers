# dispatcher

A server for asynchronous agent-to-agent task delegation and orchestration. It exposes tools to allow agents to spawn background subagents for long-running workflows, tracking job state in an SQLite database.

Installed as `mcp-dispatcher`; registered as `dispatcher`.

## Tools

### `submit_job`
Submits a new job to the dispatcher. This logs the job to the database as "Running" and asynchronously spawns a detached background `agy` process for the specified subagent worker type. The background worker is instructed to fetch its payload from the database via `get_job_status`.

**Arguments**:
- `worker_type` (string, required): The type of subagent worker to spawn (e.g. `swarm_qa`, `swarm_devlead`). Must be alphanumeric/dashes/underscores.
- `payload` (object, required): A JSON-serializable dictionary containing the task instructions, context, or data for the worker to process.

Returns the unique UUID string of the newly created job.

### `get_job_status`
Retrieves the status and original payload of a specific job from the dispatcher's database.

**Arguments**:
- `job_id` (string, required): The UUID of the job to check.

Returns a JSON object with the job's `id`, `status`, `worker_type`, the structured `payload`, and `created_at` / `updated_at` timestamps.

### `update_job_status`
Updates a job's `status` and stamps `updated_at`. This is the path a spawned worker uses to report progress. The status is validated against the `JobStatus` enum, so only known lifecycle states can be written.

**Arguments**:
- `job_id` (string, required): The UUID of the job to update.
- `status` (string, required): One of `Running`, `Completed`, or `Failed`.

Returns the updated job object, or an `error` if no job matches the id.

## Job lifecycle

Statuses are drawn from a fixed `JobStatus` enum: **`Running`** (set when `submit_job` spawns the worker), **`Completed`** (worker finished), **`Failed`** (spawn failed, or the worker reported failure). Each row also carries `created_at` and `updated_at` (UTC ISO-8601).

## Configuration

- `MCP_DISPATCHER_ALLOW_SPAWN` (Required): Must be set to `"true"` or `"1"` to allow `submit_job` to spawn background processes. If unset or false, `submit_job` will raise a runtime error. This serves as a safety guard against accidental subagent spawning.
- `MCP_DISPATCHER_DB_PATH`: Overrides the default SQLite database path (defaults to `~/.mcp/dispatcher.db`, alongside the github server's `audit.db`).

## Usage patterns

- **Long-running orchestration** — The master agent splits a complex project into discrete tasks and calls `submit_job` to assign them to specialized subagents in the background. It periodically checks on them using `get_job_status`.
- **Background workers** — The spawned `agy` process boots up with the `AGY_JOB_ID` environment variable. The background worker uses `get_job_status` to securely read its payload from the database, does its work, and calls `update_job_status` to mark the job `Completed` (or `Failed`) when finished.
