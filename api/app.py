from fastapi import FastAPI
from fastapi.responses import JSONResponse
import os, sqlite3, time

DB_PATH = os.getenv("DXSTRAT_DB", "/opt/darwinx/engine/x4pool/pool.db")
POOL_FEE_BP = int(os.getenv("POOL_FEE_BP", "200"))  # 2%
POOL_NAME = os.getenv("POOL_NAME", "Darwin X")
POOL_DOMAIN = os.getenv("POOL_DOMAIN", "pool.dxstrat.com")

app = FastAPI()

def q(sql, *args):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()

@app.get("/api/pool")
def pool():
    return {"name": POOL_NAME, "domain": POOL_DOMAIN, "fee_percent": POOL_FEE_BP / 100.0}

@app.get("/api/stats")
def stats():
    now = int(time.time())
    miners_online = q("SELECT COUNT(DISTINCT worker) AS c FROM shares WHERE accepted_ts>=?", now-600)[0]["c"]
    shares_10m = q("SELECT COUNT(*) AS c FROM shares WHERE accepted_ts>=?", now-600)[0]["c"]
    return {"miners_online": miners_online, "shares_10m": shares_10m}

@app.get("/api/miner/{address}")
def miner(address: str):
    addr = address.split(".")[0]
    rows = q("""SELECT worker, job_id, diff, accepted_ts
                FROM shares
                WHERE worker LIKE ? || '%'
                ORDER BY accepted_ts DESC
                LIMIT 100""", addr)
    return {"address": addr, "shares": [dict(r) for r in rows]}
