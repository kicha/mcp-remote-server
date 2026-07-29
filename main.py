# import random
# from fastmcp import FastMCP

# mcp = FastMCP("mcp-demo-server")

# @mcp.tool
# def add(a: int, b: int) -> int:
#     """Add two numbers."""
#     return a + b

# @mcp.tool
# def roll_dice(sides: int = 1) -> list[int]:
#     """Roll a dice with the given number of sides."""
#     return [random.randint(1, 6) for _ in range(sides)]

from fastmcp import FastMCP
import os
import sqlite3
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")

# Points to the categories JSON file — edit that file anytime, no restart needed
CATEGORIES_PATH = Path(__file__).parent / "categories.json"

mcp = FastMCP("ExpenseTracker")


def init_db():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                subcategory TEXT DEFAULT '',
                note TEXT DEFAULT ''
            )
        """)


init_db()


@mcp.tool()
def add_expense(date: str, amount: float, category: str, subcategory: str = "", note: str = "") -> dict:
    """Add a new expense record. Date should be in YYYY-MM-DD format."""
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(
            "INSERT INTO expenses(date, amount, category, subcategory, note) VALUES (?, ?, ?, ?, ?)",
            (date, amount, category, subcategory, note),
        )
        return {"status": "ok", "id": cur.lastrowid}


@mcp.tool()
def list_expenses(start_date: str | None = None, end_date: str | None = None, category: str | None = None) -> list:
    """List expenses, optionally filtered by date range (YYYY-MM-DD) and/or category."""
    query = "SELECT id, date, amount, category, subcategory, note FROM expenses WHERE 1=1"
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY date"

    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(query, params).fetchall()

    return [
        {"id": r[0], "date": r[1], "amount": r[2], "category": r[3], "subcategory": r[4], "note": r[5]}
        for r in rows
    ]


@mcp.tool()
def delete_expense(expense_id: int) -> dict:
    """Delete an expense by its id."""
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cur.rowcount == 0:
            return {"status": "not_found", "id": expense_id}
        return {"status": "deleted", "id": expense_id}


@mcp.tool()
def edit_expense(
    expense_id: int,
    date: str | None = None,
    amount: float | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    note: str | None  = None,
) -> dict:
    """Edit fields of an existing expense. Only the fields provided are updated."""
    fields, params = [], []
    for col, val in [
        ("date", date),
        ("amount", amount),
        ("category", category),
        ("subcategory", subcategory),
        ("note", note),
    ]:
        if val is not None:
            fields.append(f"{col} = ?")
            params.append(val)

    if not fields:
        return {"status": "no_changes", "id": expense_id}

    params.append(expense_id)
    with sqlite3.connect(DB_PATH) as c:
        cur = c.execute(f"UPDATE expenses SET {', '.join(fields)} WHERE id = ?", params)
        if cur.rowcount == 0:
            return {"status": "not_found", "id": expense_id}
        return {"status": "updated", "id": expense_id}


@mcp.tool()
def summarize_by_category(start_date: str | None = None, end_date: str | None = None) -> list:
    """Summarize total spend per category, optionally within a date range."""
    query = "SELECT category, SUM(amount) as total, COUNT(*) as n FROM expenses WHERE 1=1"
    params = []
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " GROUP BY category ORDER BY total DESC"

    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute(query, params).fetchall()

    return [{"category": r[0], "total": r[1], "count": r[2]} for r in rows]


@mcp.resource("expenses://categories")
def list_categories() -> list:
    """List all distinct categories currently in use."""
    with sqlite3.connect(DB_PATH) as c:
        rows = c.execute("SELECT DISTINCT category FROM expenses ORDER BY category").fetchall()
    return [r[0] for r in rows]

@mcp.resource("expense://categories", mime_type="application/json")
def categories():
    # Read fresh each time so you can edit the file without restarting
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        return f.read()

# Start the server
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
