import sqlite3, pathlib

BASE = pathlib.Path(__file__).resolve().parents[1]
DB_PATH = BASE / "db" / "pool.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS miners (
  id TEXT PRIMARY KEY,
  address TEXT,
  first_seen_ts INTEGER,
  last_seen_ts INTEGER,
  difficulty REAL,
  total_accepted INTEGER DEFAULT 0,
  total_rejected INTEGER DEFAULT 0,
  balance_sats INTEGER DEFAULT 0
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS shares (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  miner_id TEXT,
  received_ts INTEGER,
  difficulty REAL,
  valid INTEGER,
  pow_hash TEXT
)""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_shares_miner_ts ON shares(miner_id, received_ts)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_shares_ts ON shares(received_ts)")

cur.execute("""
CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  height INTEGER,
  hash TEXT,
  found_ts INTEGER,
  status TEXT,
  template_prevhash TEXT,
  reward_sats INTEGER
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  miner_id TEXT,
  created_ts INTEGER,
  prevhash TEXT,
  version TEXT,
  nbits TEXT,
  ntime TEXT,
  merkle_root TEXT,
  clean_jobs INTEGER,
  exclusive INTEGER,
  used INTEGER DEFAULT 0
)""")

cur.execute("""
CREATE TABLE IF NOT EXISTS engine_stats (
  id INTEGER PRIMARY KEY CHECK (id=1),
  template_prevhash TEXT,
  template_height INTEGER,
  started_ts INTEGER,
  pool_size_current INTEGER,
  generated_since_template INTEGER,
  top_score REAL,
  top_hash_norm REAL,
  top_entropy REAL,
  w_hash REAL,
  w_ent REAL,
  last_update INTEGER,
  top_list TEXT
)""")
cur.execute("CREATE TABLE IF NOT EXISTS engine_stats_series (ts INTEGER, generated_since_template INTEGER)")

con.commit()
con.close()
print(f"OK: migrated {DB_PATH}")
