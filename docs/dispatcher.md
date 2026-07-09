# dispatcher

Asynchronous agent-to-agent task delegation and orchestration: agents queue jobs for standing workers to pull and execute, with job state tracked in an SQLite database.

Installed as `mcp-dispatcher`; registered as `dispatcher`.

## Tools

### `submit_job`
Log a new job as `Queued` for standing agents to claim. Returns the new job's UUID.

**Arguments**:
- `worker_type` (string, required): The type of worker to handle this job (e.g. `swarm_qa`, `devlead`). Alphanumeric, dashes, and underscores only.
- `payload` (object, required): JSON-serializable task instructions, context, or data for the worker.
- `parent_id` (string, optional): Optional ID of a parent task to link subtasks.

### `claim_job`
Finds the oldest `Queued` job matching the given `worker_type`, sets its status to `Running`, and records the claiming agent. Returns the job object or null.

**Arguments**:
- `worker_type` (string, required): The type of worker looking for a job.
- `agent_id` (string, required): ID of the specific standing agent process claiming the job.

### `get_job_status`
Retrieve one job's status and original payload.

**Arguments**:
- `job_id` (string, required): The UUID of the job to fetch.

Returns a JSON object with the job's `id`, `status`, `worker_type`, `payload`, `result`, `claimed_by`, `parent_id`, and `created_at` / `updated_at` timestamps.

### `update_job_status`
Set a job's `status`, optionally record a `result`, and stamp `updated_at` — the path a worker uses to report progress. The status is validated against the `JobStatus` enum, and terminal states are immutable.

**Arguments**:
- `job_id` (string, required): The UUID of the job to update.
- `status` (string, required): New status for the job.
- `result` (object, optional): Optional JSON-serializable task outputs/feedback.

### `heartbeat_job`
Update the `updated_at` timestamp for a job to signal the worker is still active.

**Arguments**:
- `job_id` (string, required): The ID of the job to heartbeat.

### `requeue_stalled_jobs`
Find jobs that are `Running` but haven't been updated recently, and reset them to `Queued`.

**Arguments**:
- `timeout_minutes` (integer, required): Jobs with an `updated_at` older than this many minutes will be requeued.

### `send_message`
Append a message to a job's conversation history.

**Arguments**:
- `job_id` (string, required): The ID of the job this message is associated with.
- `sender` (string, required): The agent sending the message (e.g. 'architect', 'devlead').
- `recipient` (string, required): The target agent or 'all'.
- `content` (string, required): The markdown content of the message.

### `get_messages`
Retrieve messages for a job.

**Arguments**:
- `job_id` (string, required): The ID of the job.
- `since` (string, optional): Optional ISO-8601 timestamp. Only messages created after this will be returned.

### `list_jobs`
List jobs, newest first.

**Arguments**:
- `status` (string, optional): Filter to a single `JobStatus`.
- `limit` (integer, optional): Maximum jobs to return (default `50`, range 1–500).

### `cleanup_jobs`
Delete terminal (`Completed`, `Failed`, `Cancelled`) jobs.

**Arguments**:
- `older_than_days` (integer, optional): Only delete terminal jobs whose last update is older than this many days. Omit to delete all terminal jobs.

## Job lifecycle

Statuses come from a fixed `JobStatus` enum: **`Queued`** (waiting for a worker), **`Running`** (claimed and executing), **`InReview`** (worker finished, pending architect review), **`ChangesRequested`** (architect returned feedback), **`Completed`** (approved and merged), **`Failed`** (error condition), and **`Cancelled`**.

Each row also carries `created_at` and `updated_at` (UTC ISO-8601), plus `claimed_by` and `parent_id`. Terminal states (`Completed`, `Failed`, `Cancelled`) cannot be changed once set.

## Configuration

- `MCP_DISPATCHER_DB_PATH`: SQLite database path (default `~/.mcp/dispatcher.db`, alongside the github server's `audit.db`).

## Usage patterns

- **Master orchestration** — the master agent splits a project into discrete tasks, calls `submit_job` for each (which queues them), checks progress via `list_jobs`, and reviews completed work moving it to `Completed` or `ChangesRequested`.
- **Standing workers** — standing agent processes run an event loop: `claim_job` -> execute payload, calling `heartbeat_job` periodically -> finish via `update_job_status(..., "InReview", result={...})`.
