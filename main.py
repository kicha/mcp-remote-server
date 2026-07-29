"""
Expense tracker MCP server — Supabase Postgres, async version (asyncpg)

Changes vs. the earlier sync version:
- All tools are now `async def`, using asyncpg + a shared connection pool
  instead of opening a new psycopg2 connection per call.
- date is stored as TEXT (not DATE) and amount is cast to float8 on read.
  This matches your original SQLite behavior (plain "YYYY-MM-DD" strings,
  plain floats) and avoids MCP response serialization errors, since raw
  asyncpg `date`/`Decimal` objects aren't JSON-serializable by default.
- statement_cache_size=0 is required when pointed at Supabase's
  TRANSACTION-mode pooler (port 6543) — that pooler doesn't support
  server-side prepared statements, which asyncpg uses by default.

DATABASE_URL:
  Format (transaction pooler — recommended for FastMCP Cloud's short-lived
  containers):

    
  postgresql://postgres.xjpndlrmknrxqflpeswl:@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres
  Where to get the real values: Supabase dashboard -> your project ->
  "Connect" button -> copy the "Transaction pooler" string, then fill in
  your database password (Project Settings -> Database -> Reset database
  password if you don't have it — this is separate from your Supabase
  account login).

  Set this as the DATABASE_URL environment variable in FastMCP Cloud's
  project settings — do not hardcode it or commit it to git.

  Gotcha: if your password contains special characters (@, :, /, #, etc.),
  URL-encode them or the connection string will fail to parse.
"""

import os
from typing import Optional

import asyncpg
from fastmcp import FastMCP

mcp = FastMCP("expense-tracker")

DATABASE_URL = os.environ["DATABASE_URL"]  # fails fast at startup if unset

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    pool = _pool  # work with a local; Pylance narrows locals reliably across awaits, unlike globals
    if pool is None:
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            statement_cache_size=0,  # required for Supabase transaction-mode pooler
        )
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id SERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    amount NUMERIC NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
            """)
        _pool = pool  # write back to the global once, after it's fully initialized
    return pool


@mcp.tool
async def add_expense(amount: float, category: str, date: str, note: str = "", subcategory: str = "") -> dict:
    """Add a new expense record. Date should be in YYYY-MM-DD format."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        new_id = await conn.fetchval(
            "INSERT INTO expenses (date, amount, category, subcategory, note) "
            "VALUES ($1, $2, $3, $4, $5) RETURNING id",
            date, amount, category, subcategory, note,
        )
    return {"status": "ok", "id": new_id}


@mcp.tool
async def delete_expense(expense_id: int) -> dict:
    """Delete an expense by its id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM expenses WHERE id = $1", expense_id)
    deleted = result.split()[-1] != "0"  # asyncpg returns e.g. "DELETE 1"
    return {"status": "ok", "deleted": deleted}


@mcp.tool
async def edit_expense(
    expense_id: int,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    date: Optional[str] = None,
    note: Optional[str] = None,
    subcategory: Optional[str] = None,
) -> dict:
    """Edit fields of an existing expense. Only the fields provided are updated."""
    fields, values = [], []
    for col, val in [("amount", amount), ("category", category), ("date", date),
                      ("note", note), ("subcategory", subcategory)]:
        if val is not None:
            values.append(val)
            fields.append(f"{col} = ${len(values)}")
    if not fields:
        return {"status": "noop"}
    values.append(expense_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = ${len(values)}", *values)
    return {"status": "ok"}


@mcp.tool
async def list_expenses(category: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None) -> list:
    """List expenses, optionally filtered by date range (YYYY-MM-DD) and/or category."""
    conditions, values = [], []
    if category:
        values.append(category)
        conditions.append(f"category = ${len(values)}")
    if start_date:
        values.append(start_date)
        conditions.append(f"date >= ${len(values)}")
    if end_date:
        values.append(end_date)
        conditions.append(f"date <= ${len(values)}")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, date, amount::float8 AS amount, category, subcategory, note "
            f"FROM expenses {where} ORDER BY date",
            *values,
        )
    return [dict(r) for r in rows]


@mcp.tool
async def summarize_by_category(start_date: Optional[str] = None, end_date: Optional[str] = None) -> list:
    """Summarize total spend per category, optionally within a date range."""
    conditions, values = [], []
    if start_date:
        values.append(start_date)
        conditions.append(f"date >= ${len(values)}")
    if end_date:
        values.append(end_date)
        conditions.append(f"date <= ${len(values)}")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT category, SUM(amount)::float8 AS total FROM expenses {where} "
            f"GROUP BY category ORDER BY total DESC",
            *values,
        )
    return [dict(r) for r in rows]


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)