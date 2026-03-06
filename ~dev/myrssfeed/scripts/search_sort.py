from fastapi import FastAPI, Query
import sqlite3

app = FastAPI()
DB_FILE = "feeds/rss.db"

@app.get("/search")
def search_entries(q: str = "", sort_by: str = "published", limit: int = 50):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Simple search
    cursor.execute(f"""
        SELECT title, link, published FROM entries
        WHERE title LIKE ? OR summary LIKE ?
        ORDER BY {sort_by} DESC
        LIMIT ?
    """, (f"%{q}%", f"%{q}%", limit))

    results = cursor.fetchall()
    conn.close()
    return {"results": results}

