import sqlite3, os, time
from contextlib import contextmanager

DB_PATH = os.getenv("DXSTRAT_DB", "/opt/darwinx/engine/x4pool/pool.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS miners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  worker TEXT UNIQUE,
  first_seen_ts INTEGER NOT NULL,
  last_seen_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  worker TEXT NOT NULL,
  job_id TEXT NOT NULL,
  diff REAL NOT NULL,
  accepted_ts INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shares_ts ON shares(accepted_ts);
CREATE INDEX IF NOT EXISTS idx_shares_worker ON shares(worker);

CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  height INTEGER NOT NULL,
  bhash TEXT NOT NULL,
  reward_sats INTEGER NOT NULL,
  finder TEXT NOT NULL,
  ts INTEGER NOT NULL,
  matured INTEGER NOT NULL DEFAULT 0,
  paid INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_blocks_hash ON blocks(bhash);
"""

def init():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SCHEMA)

@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()

def upsert_miner(worker: str):
    now = int(time.time())
    with db() as con:
        con.execute("""
            INSERT INTO miners(worker, first_seen_ts, last_seen_ts)
            VALUES(?,?,?)
            ON CONFLICT(worker) DO UPDATE SET last_seen_ts=excluded.last_seen_ts
        """, (worker, now, now))

def insert_share(worker: str, job_id: str, diff: float):
    now = int(time.time())
    with db() as con:
        con.execute("INSERT INTO shares(worker, job_id, diff, accepted_ts) VALUES(?,?,?,?)",
                    (worker, job_id, diff, now))

def insert_block(height: int, bhash: str, reward_sats: int, finder: str):
    now = int(time.time())
    with db() as con:
        con.execute("""
            INSERT OR IGNORE INTO blocks(height, bhash, reward_sats, finder, ts)
            VALUES(?,?,?,?,?)
        """, (height, bhash, reward_sats, finder, now))
