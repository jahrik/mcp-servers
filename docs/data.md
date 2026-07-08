# data

Local data analysis for AI agents without burning context: run SQL over large local files
(CSV, JSON, JSONL, Parquet) in place, and keep scratch tables alive across tool calls —
working memory outside the context window. This is not a general database connector; it is
an agent tool for pushing computation to the data and pulling back only the answer rows.

DuckDB is the engine, which is why the tools keep the `duckdb_*` prefix: the name tells the
agent which SQL dialect applies and that file-query idioms like `SELECT * FROM 'file.csv'` work.

Installed as `mcp-data`; registered as `data`.

## Behavior

- **Direct file querying** — query large CSV, JSON, JSONL, and Parquet files with SQL without loading them into the agent context (e.g. `SELECT * FROM 'logs.json' WHERE level = 'error'`).
- **Scratch databases** — build in-memory or persistent databases on the fly to hold intermediate results or state across tool calls.
- **Connection caching** — `:memory:` state, schemas, and loaded extensions are retained across separate calls.
- **Concurrency** — a per-database-path lock serializes concurrent operations.
- **Resource controls** — configurable memory limit, query timeout, and external-access toggle (see [Configuration](#configuration)).
- **Error diagnostics** — errors include suggestions for missing tables, wrong file paths, or syntax issues.

## Tools

### `duckdb_query`
Execute a SQL query against DuckDB. Supports both read-only queries (`SELECT`) and mutations (`CREATE`, `INSERT`, `UPDATE`, `DROP`, `COPY`).

**Arguments**:
- `query` (string, required): The SQL query to run.
- `database` (string, optional): Path to a persistent DuckDB database file (e.g., `data.db`). If omitted, runs against a temporary in-memory database.
- `read_only` (boolean, optional): Connect to the database in read-only mode. Defaults to `false`.
- `max_rows` (integer, optional): Maximum rows to return (default `2000`). Automatically truncates results to prevent context window overflow. The rendered output is additionally capped at `MCP_DATA_MAX_CHARS` characters (default `100000`) — wide rows are trimmed further, and a single row over the budget returns an error suggesting narrower columns or aggregation.

### `duckdb_describe`
Get the schema (columns, types, nullability) of a file or table.

**Arguments**:
- `path` (string, required): Path to a CSV, JSON, Parquet file, or table/view name to describe.
- `database` (string, optional): Path to a persistent DuckDB database file (optional).

### `duckdb_list_tables`
List all tables and views across every schema in the database. Names outside the `main` schema come back schema-qualified (e.g. `stats.runs`).

**Arguments**:
- `database` (string, optional): Path to a persistent DuckDB database file (optional).

### `duckdb_close_database`
Close and release the connection and file lock for a database.

**Arguments**:
- `database` (string, optional): Path to the database connection to close. If omitted, closes the in-memory database.

## Configuration

Configuration parameters are read from environment variables:

- `MCP_DUCKDB_MEMORY_LIMIT`: Restricts memory allocated to DuckDB (e.g., `4GB`, `512MB`). Defaults to `2GB` to prevent query tasks from causing system Out-Of-Memory events. Values that don't look like a size fall back to the default.
- `MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS`: Set to `true` to enable `SET enable_external_access = false`. **This blocks all file access — local CSV/JSON/Parquet files as well as remote HTTPS/S3 resources — and `ATTACH`/extension loading.** Since querying local files is this server's primary purpose, leave it `false` unless you specifically want a SQL-only sandbox over already-created tables. Defaults to `false`.
- `MCP_DATA_MAX_CHARS`: Total character budget for a query result (default `100000`). `max_rows` caps rows, not bytes; this caps the rendered JSON so wide text columns cannot flood the agent's context window.
- `MCP_DATA_QUERY_TIMEOUT`: Seconds before a running query is interrupted (default `60`, `0` disables). Stops runaway SQL (an accidental cross join over a large file) from blocking the server indefinitely.

## Type serialization

Result cells are rendered to JSON as follows:

- `DATE`/`TIME`/`TIMESTAMP`/`TIMESTAMPTZ` → ISO-8601 strings
- `DECIMAL` → float (lossy above ~15 significant digits — cast to `VARCHAR` in SQL if exact digits matter)
- `HUGEINT`/`UHUGEINT` → JSON integer (exact here, but beyond 2^53 it will lose precision in JavaScript-based consumers)
- `BLOB` → UTF-8 with replacement characters
- `NaN`/`Infinity` floats → the strings `"nan"`/`"inf"`/`"-inf"` (raw JSON `NaN` is not valid JSON)
- `LIST`/`STRUCT`/`MAP` → JSON arrays/objects
- `UUID`, `INTERVAL`, and any other type → their string representation

## Token savings in practice

The point of the server is to keep large payloads out of the agent's context: it processes
the file natively and returns only the answer rows. Three measured runs, from a GitHub API
payload up to 50M synthetic rows (tokens ≈ bytes ÷ 4; DuckDB is bundled, so no CLI is needed):

| Source | Size on disk | ~Tokens if read into context | Query → result | ~Result tokens | Reduction |
|--------|-------------:|-----------------------------:|----------------|---------------:|----------:|
| **GitHub API** — `users/jahrik/repos` JSON | 381 KB | ~95K | language analytics → 11 rows | ~200 | **~475 : 1** |
| **Synthetic** — `events.jsonl`, 10M rows | 1.40 GB | ~366M | revenue by type/region → 8 rows | ~360 | **~1,000,000 : 1** |
| **Cold-agent test** — `sales.csv`, 6K rows | 199 KB | ~51K | top-3 regions by revenue → 3 rows | ~50 | **~1,000 : 1** |

The synthetic file is 1,800× larger than a 200K-token context window — it *cannot* be read
in at all, so the server is not just cheaper here but the only way to answer. The cold-agent
row is the smallest but the most telling: an unprimed agent, handed only the file path and a
question, chose `duckdb_query` over reading the file on its own.

## Usage examples

### 1. In-memory key-value state
Create a schema and store key-value data in the cached in-memory database:
```sql
CREATE TABLE IF NOT EXISTS kv_store (key VARCHAR PRIMARY KEY, value JSON);
INSERT OR REPLACE INTO kv_store VALUES ('preferences', '{"theme": "dark"}');
SELECT * FROM kv_store;
```

### 2. Querying a local file
Inspect and query a local CSV file directly from the filesystem:
```sql
SELECT count(*), avg(salary) FROM '/path/to/employees.csv' WHERE department = 'Engineering';
```

### 3. Federated query
Join a local CSV file with an existing SQLite database file (via the `sqlite` extension):
```sql
INSTALL sqlite;
LOAD sqlite;
ATTACH '/path/to/production.db' AS sqlite_db (TYPE SQLITE);

SELECT csv.name, sqlite_db.users.email
FROM '/path/to/offline_registrations.csv' csv
JOIN sqlite_db.users ON csv.id = sqlite_db.users.id;
```

### 4. Vector / semantic memory search
Using the native `vss` extension for vector embeddings:
```sql
INSTALL vss;
LOAD vss;

CREATE TABLE IF NOT EXISTS embeddings_store (
    id VARCHAR PRIMARY KEY,
    content TEXT,
    embedding FLOAT[1536]
);

-- Query the 5 closest records by Cosine similarity
-- SELECT content FROM embeddings_store ORDER BY array_cosine_distance(embedding, ?) LIMIT 5;
```
