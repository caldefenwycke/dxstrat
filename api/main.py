from fastapi import FastAPI, Response, HTTPException
import sqlite3, json, time, math, os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_PATH = os.path.join(BASE_DIR, "db", "pool.db")
CFG_PATH = os.path.join(BASE_DIR, "config", "config.json")

app = FastAPI(title="DarwinXPool API")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------- Health & Pool Stats ----------
@app.get("/health")
def health():
    return {"ok": True, "time": int(time.time()), "db_exists": os.path.exists(DB_PATH)}

@app.get("/pool")
def pool_info():
    # minimal pool summary – expand later with hashrate, fee, etc.
    return {"name": "DarwinX Pool", "domain": "dxstrat.com", "fee_percent": 2.0}

@app.get("/stats")
def stats():
    with db() as c:
        miners = c.execute("SELECT COUNT(*) AS c FROM miners").fetchone()["c"]
        shares = c.execute("SELECT COUNT(*) AS c FROM shares").fetchone()["c"]
        blocks = c.execute("SELECT COUNT(*) AS c FROM blocks").fetchone()["c"]
        bal = c.execute("SELECT COALESCE(SUM(balance_sats),0) AS t FROM miners").fetchone()["t"]
    return {"miners": miners, "shares": shares, "blocks": blocks, "total_balance_sats": bal}

@app.get("/")
def root():
    return {"ok": True, "name": "DarwinXPool API", "routes": ["/health","/stats","/miner","/darwinx"]}

@app.get("/blocks")
def blocks_list(limit: int = 50):
    limit = max(1, min(200, int(limit)))
    with db() as c:
        rows = c.execute("""
            SELECT height, hash, found_ts, status, reward_sats
            FROM blocks
            ORDER BY found_ts DESC NULLS LAST, height DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return {"items": [dict(r) for r in rows]}

# ---------- Public Pages ----------
with open(os.path.join(os.path.dirname(__file__), "miner.html"), "r", encoding="utf-8") as f:
    MINER_HTML = f.read()
with open(os.path.join(os.path.dirname(__file__), "darwinx.html"), "r", encoding="utf-8") as f:
    DARWINX_HTML = f.read()

@app.get("/miner")
def miner_page():
    return Response(content=MINER_HTML, media_type="text/html")

@app.get("/darwinx")
def darwinx_page():
    return Response(content=DARWINX_HTML, media_type="text/html")

# ---------- Miner JSON ----------
@app.get("/miners")
def miners():
    with db() as c:
        rows = c.execute("""
            SELECT id,address,last_seen_ts,difficulty,total_accepted,total_rejected,balance_sats
            FROM miners
            ORDER BY last_seen_ts DESC LIMIT 500
        """).fetchall()
    return {"miners": [dict(r) for r in rows]}

@app.get("/miner/{address}")
def miner_stats(address: str):
    now = int(time.time())
    window_secs = 600
    with db() as c:
        m = c.execute("SELECT id,address,last_seen_ts,difficulty,total_accepted,total_rejected,balance_sats FROM miners WHERE address=? OR id LIKE ? LIMIT 1", (address, address+'%')).fetchone()
        if not m:
            return {"ok": False, "error": "not_found"}
        rows = c.execute("SELECT difficulty, valid, received_ts FROM shares WHERE miner_id=? AND received_ts>=? AND valid=1", (m["id"], now - window_secs)).fetchall()
        diff_sum = sum(r["difficulty"] for r in rows) if rows else 0.0
        hashrate = (diff_sum * (2**32)) / window_secs if window_secs>0 else 0.0
        last_share = c.execute("SELECT MAX(received_ts) AS ts FROM shares WHERE miner_id=?", (m["id"],)).fetchone()["ts"]
        return {
            "ok": True,
            "id": m["id"], "address": m["address"],
            "last_seen_ts": m["last_seen_ts"], "difficulty": m["difficulty"],
            "total_accepted": m["total_accepted"], "total_rejected": m["total_rejected"],
            "balance_sats": m["balance_sats"], "hashrate_hs": hashrate,
            "window_seconds": window_secs, "last_share_ts": last_share
        }

@app.get("/miner/{address}/shares")
def miner_shares(address: str, limit: int = 100):
    limit = max(1, min(500, int(limit)))
    with db() as c:
        m = c.execute("SELECT id FROM miners WHERE address=? OR id LIKE ? LIMIT 1", (address, address+'%')).fetchone()
        if not m: return {"items": []}
        rows = c.execute("""
            SELECT received_ts, valid, difficulty, pow_hash
            FROM shares WHERE miner_id=?
            ORDER BY received_ts DESC LIMIT ?
        """, (m["id"], limit)).fetchall()
    return {"items": [dict(r) for r in rows]}

@app.get("/miner/{address}/hashrate24h")
def miner_hashrate_24h(address: str, bucket_minutes: int = 5):
    bucket_minutes = max(1, min(60, int(bucket_minutes)))
    bucket_secs = bucket_minutes * 60
    now = int(time.time()); start = now - 24*3600
    with db() as c:
        m = c.execute("SELECT id FROM miners WHERE address=? OR id LIKE ? LIMIT 1", (address, address+'%')).fetchone()
        if not m: return {"bucket_seconds": bucket_secs, "labels": [], "hashrate_hs": []}
        rows = c.execute("SELECT received_ts, difficulty FROM shares WHERE miner_id=? AND valid=1 AND received_ts>=? ORDER BY received_ts ASC", (m["id"], start)).fetchall()
    n_b = math.ceil((24*3600)/bucket_secs)
    buckets = [0.0]*n_b; t0 = start - (start % bucket_secs)
    for r in rows:
        idx = (r["received_ts"] - t0)//bucket_secs
        if 0 <= idx < n_b: buckets[int(idx)] += float(r["difficulty"])
    labels = [t0 + i*bucket_secs for i in range(n_b)]
    rates = [(d*(2**32))/bucket_secs for d in buckets]
    return {"bucket_seconds": bucket_secs, "labels": labels, "hashrate_hs": rates}

@app.get("/miner/{address}/shares/timeline")
def miner_share_timeline(address: str, hours: int = 24):
    hours = max(1, min(72, int(hours)))
    start = int(time.time()) - hours*3600
    with db() as c:
        m = c.execute("SELECT id FROM miners WHERE address=? OR id LIKE ? LIMIT 1", (address, address+'%')).fetchone()
        if not m: return {"items": []}
        rows = c.execute("SELECT received_ts, valid, difficulty FROM shares WHERE miner_id=? AND received_ts>=? ORDER BY received_ts ASC", (m["id"], start)).fetchall()
    return {"items": [dict(r) for r in rows]}

# ---------- DarwinX live ----------
@app.get("/darwinx/stats")
def darwinx_stats():
    with db() as c:
        row = c.execute("""
            SELECT template_prevhash, template_height, started_ts, pool_size_current,
                   generated_since_template, top_score, top_hash_norm, top_entropy,
                   w_hash, w_ent, last_update, top_list
            FROM engine_stats WHERE id=1
        """).fetchone()
        if not row: return {"ok": False}
        d = dict(row)
        try:
            d["top_list"] = json.loads(d.get("top_list") or "[]")
        except Exception:
            d["top_list"] = []
    return {"ok": True, **d}

@app.get("/darwinx/series")
def darwinx_series(minutes: int = 60):
    minutes = max(1, min(720, int(minutes)))
    since = int(time.time()) - minutes*60
    with db() as c:
        rows = c.execute(
            "SELECT ts, generated_since_template FROM engine_stats_series WHERE ts>=? ORDER BY ts ASC",
            (since,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


