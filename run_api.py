# run_api.py  (keep this — useful for local dev)
import asyncio
import aiosqlite
import uvicorn
from db.schema import init_db
from db.repository import Repository
from api.main import create_app

async def build_app():
    conn = await aiosqlite.connect("db/trades.db")
    await init_db(conn)
    repo = Repository(conn)
    return create_app(repo)

if __name__ == "__main__":
    import os
    os.makedirs("db", exist_ok=True)
    app = asyncio.run(build_app())
    uvicorn.run(app, host="0.0.0.0", port=8000)
