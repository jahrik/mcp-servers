# MCP-Memory Server Stress Test Results

This document presents the methodology, findings, metrics, and recommendations from a comprehensive stress test executed on the **mcp-memory** server.

---

## 1. Executive Summary

The `mcp-memory` server was subjected to a high-concurrency, volume-intensive stress test targeting the DuckDB database backend.

### Key Findings
* **Read/Write Concurrency is High:** Once the database is initialized, DuckDB handles concurrent inserts to different keys seamlessly. A test with **150 concurrent writes** completed in **0.77 seconds** with a 100% success rate.
* **Database Initialization Conflict:** When starting on a clean/non-existent database, concurrent write requests encounter catalog write-write conflicts (`TransactionContext Error: Catalog write-write conflict on create...`) because multiple threads try to run `CREATE TABLE IF NOT EXISTS` at the exact same moment.
* **Key Update/Conflict Bottleneck:** Multiple concurrent writes to the *same key* yield unique constraint violations and transaction conflicts (`TransactionContext Error: Conflict on tuple deletion!`). The current backoff/retry loop does not catch these errors, resulting in a **58% failure rate** under high key contention.
* **Excellent Large Payload Performance:** The server scales exceptionally well with size. Storing a **5 MB text payload** took only **0.13 seconds**, and recalling it took **0.10 seconds** with 100% data integrity.

---

## 2. Stress Test Metrics

Below are the detailed metrics collected from running concurrency, conflict, and large payload tests.

### Concurrency Performance (Distinct Keys)
| Concurrency Level (Tasks) | Operation Type | Success Rate | Total Time (s) | Average Latency (s) | Notes / Errors |
|:---|:---|:---|:---|:---|:---|
| **10** | Write | 10% (1/10) | 0.0745 | 0.0345 | Catalog write-write conflict (schema initialization) |
| **10** | Read (Recall) | 100% (10/10) | 0.0414 | 0.0362 | Healthy |
| **50** | Write | 100% (50/50) | 0.3345 | 0.1872 | Healthy (schema already exists) |
| **50** | Read (Recall) | 100% (50/50) | 0.1175 | 0.0756 | Healthy |
| **100** | Write | 100% (100/100) | 0.5271 | 0.2678 | Healthy |
| **100** | Read (Recall) | 100% (100/100) | 0.2684 | 0.1550 | Healthy |
| **150** | Write | 100% (150/150) | 0.7715 | 0.3923 | Healthy |
| **150** | Read (Recall) | 100% (150/150) | 0.4871 | 0.2652 | Healthy |

### Key Conflict Writes (Same Key)
| Conflicting Tasks | Success Rate | Total Time (s) | Average Latency (s) | Primary Errors |
|:---|:---|:---|:---|:---|
| **50** | **42% (21/50)** | 0.2515 | 0.1438 | `Constraint Error: Duplicate key "key: conflict_key"` <br>`TransactionContext Error: Conflict on tuple deletion!` |

### Large Payload Scaling
| Payload Size | Write Time (s) | Write Status | Read Time (s) | Read Status |
|:---|:---|:---|:---|:---|
| **10 KB** | 0.0646 | Success | 0.0265 | Success |
| **100 KB** | 0.0764 | Success | 0.0255 | Success |
| **1000 KB (1 MB)** | 0.0906 | Success | 0.0421 | Success |
| **5000 KB (5 MB)** | 0.1331 | Success | 0.1024 | Success |

---

## 3. Detailed Technical Analysis

### Issue A: Schema Initialization Write-Write Conflict
* **Symptoms:** When the database starts from scratch, concurrent writes trigger `TransactionContext Error: Catalog write-write conflict on create with "Schema\0main\0main\0Table\0main\0memories"`.
* **Root Cause:** In [db.py](file:///home/deck/github/mcp-servers/src/mcp_servers/memory/tools/db.py#L58), `init_db(conn)` is called lazily on the first write connection. When multiple threads launch write connections simultaneously, they all try to create the tables/indices concurrently. DuckDB's catalog updates are serializable, causing concurrent creation transactions to conflict and abort.
* **Why the retry logic failed:** The retry handler in [db.py](file:///home/deck/github/mcp-servers/src/mcp_servers/memory/tools/db.py#L65) only retries on exceptions containing `"lock"`, `"permission"`, or `"resource temporarily unavailable"`. Catalog write-write conflict errors do not match these criteria.

### Issue B: MVCC & Unique Constraint Conflict on Key Updates
* **Symptoms:** Concurrent writes to the same key yield a 58% failure rate with `TransactionContext Error: Conflict on tuple deletion!` and unique constraint errors.
* **Root Cause:**
  1. **MVCC conflicts:** If two transactions try to update/delete the same row concurrently, the database aborts one of them to prevent write skew.
  2. **Unique constraint conflicts:** When keys do not exist, concurrent threads query if the key exists (returns `None`), and then proceed to `INSERT`. The first one to commit succeeds, while the rest fail with a primary key unique constraint error.
* **Why the retry logic failed:** These exceptions are raised as `duckdb.ConstraintException` or `duckdb.TransactionException` and their messages do not contain `"lock"`. They bypass the retry logic and fail immediately.

---

## 4. Recommendations & Fixes

### Recommendation 1: Initialize Schema on Server Startup (High Priority)
To eliminate catalog write-write conflicts entirely, the database should be initialized once sequentially when the server starts, rather than lazily during the first client query.

**Proposed Implementation:**
Initialize the database in the console script entry point `main()` in [server.py](file:///home/deck/github/mcp-servers/src/mcp_servers/memory/server.py).
```python
def main() -> None:
    # ...
    # Initialize database schema sequentially before starting the server
    from .tools.db import get_db_conn
    with get_db_conn(read_only=False) as conn:
        pass # get_db_conn automatically runs init_db(conn)
    # ...
    mcp.run()
```

### Recommendation 2: Expand Database Retry Exception Matching (High Priority)
Update the database connection retry loop to catch transaction conflicts and constraint violations. This will enable transient MVCC update conflicts and insert conflicts to automatically retry, back off, and succeed.

**Proposed Implementation:**
Modify [db.py](file:///home/deck/github/mcp-servers/src/mcp_servers/memory/tools/db.py) to catch `conflict`, `transaction`, and `constraint` error substrings:
```python
            err_msg = str(e).lower()
            if (
                "lock" in err_msg
                or "permission" in err_msg
                or "resource temporarily unavailable" in err_msg
                or "conflict" in err_msg
                or "constraint" in err_msg
            ):
```
This change will resolve both the key conflict constraint violations (by causing the retried transaction to perform an `UPDATE` instead of `INSERT`) and MVCC update conflicts.

---

## 5. Active Database Verification & Sync Results

A live database sync was triggered using the `sync_existing_data` tool to import historical context.

### Import Statistics
* **Total Records Synced:** 54
* **Brain Artifacts:** 3
* **Conversation Summaries:** 48
* **Claude sessions:** 3

### Database Peeking (`duckdb_describe` on `memories` table)
Running `duckdb_describe` on `/home/deck/.mcp/memory.db` confirms the exact schema structure created:
```json
[
  {"column_name": "id", "column_type": "VARCHAR", "null": "NO", "key": "PRI"},
  {"column_name": "key", "column_type": "VARCHAR", "null": "YES", "key": "UNI"},
  {"column_name": "content", "column_type": "VARCHAR", "null": "NO"},
  {"column_name": "category", "column_type": "VARCHAR", "null": "YES"},
  {"column_name": "tags", "column_type": "VARCHAR", "null": "YES"},
  {"column_name": "embedding", "column_type": "FLOAT[]", "null": "YES"},
  {"column_name": "created_at", "column_type": "TIMESTAMP", "null": "YES", "default": "CURRENT_TIMESTAMP"},
  {"column_name": "updated_at", "column_type": "TIMESTAMP", "null": "YES", "default": "CURRENT_TIMESTAMP"}
]
```

### Data Categorization metrics
```sql
SELECT category, count(*) as count, avg(length(content))::INTEGER as avg_len
FROM memories GROUP BY category ORDER BY count DESC;
```
Yields:
1. **`conversation_summary`**: 48 entries (avg length = 281 characters)
2. **`claude_session`**: 3 entries (avg length = 25,320 characters)
3. **`artifact`**: 3 entries (avg length = 4,856 characters)

The active long-term memory server is fully synced, verified, and ready for use.
