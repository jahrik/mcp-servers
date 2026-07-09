from __future__ import annotations

import asyncio
import json

from ..models.schemas import ForgetArgs
from .db import get_db_conn, rebuild_fts_index


def _execute_forget(args: ForgetArgs) -> str:
    if not args.key and not args.id:
        return json.dumps(
            {
                "status": "error",
                "message": "Either 'key' or 'id' must be specified to forget a memory.",
            }
        )

    # DuckDB returns the affected-row count as a one-row result set for DELETE, which
    # is what we read below. (DB-API cursor.rowcount is unreliable in DuckDB, so it is
    # intentionally not used; this couples forget to DuckDB, which is the only backend.)
    with get_db_conn(read_only=False) as conn:
        if args.id:
            res = conn.execute("DELETE FROM memories WHERE id = ?", [args.id]).fetchall()
            rows_deleted = res[0][0] if res else 0
            target = f"id '{args.id}'"
        else:
            res = conn.execute("DELETE FROM memories WHERE key = ?", [args.key]).fetchall()
            rows_deleted = res[0][0] if res else 0
            target = f"key '{args.key}'"

        # Keep BM25 statistics accurate after a deletion.
        if rows_deleted > 0:
            rebuild_fts_index(conn)

    if rows_deleted > 0:
        return json.dumps(
            {
                "status": "success",
                "message": f"Successfully deleted memory with {target}.",
                "deleted": True,
            }
        )
    else:
        return json.dumps(
            {
                "status": "success",
                "message": f"No memory found matching {target}.",
                "deleted": False,
            }
        )


async def forget(args: ForgetArgs) -> str:
    """Delete a fact or preference from long-term memory using its key or database ID.

    Args:
        key: The key of the memory to delete.
        id: The database ID of the memory to delete.
    """
    return await asyncio.to_thread(_execute_forget, args)
