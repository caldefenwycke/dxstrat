import os, time, sqlite3
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.responses import JSONResponse

load_dotenv("config/.env")
DB_PATH = os.getenv("DB_PATH","./pool.db")

app = FastAPI(title="DarwinX Pool API")

def db():
    con = sqlite3.connect(DB_PATH)
    return con

@app.get("/api/stats")
def stats():
    con = db(); cur = con.cursor()
    now = int(time.time())
    since = now - 86400
    shares_24h = cur.execute("SELECT COUNT(*) FROM shares WHERE ts>=?", (since,)).fetchone()[0]
    miners_online = cur.execute("SELECT COUNT(*) FROM miners WHERE last_seen_ts>=?", (now-60,)).fetchone()[0]
    # naive hashrate estimator: accepted shares * diff1 / 600s window (rough)
    # (left as simple counter)
    con.close()
    return {"miners_online": miners_online, "shares_24h": shares_24h, "time": now}
