PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS miners(
  id TEXT PRIMARY KEY,                 -- "wallet.worker"
  wallet TEXT NOT NULL,                -- parsed wallet address
  worker TEXT NOT NULL,
  first_seen_ts INTEGER NOT NULL,
  last_seen_ts  INTEGER NOT NULL,
  vardiff REAL NOT NULL DEFAULT 1.0,
  total_accepted INTEGER NOT NULL DEFAULT 0,
  total_rejected INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rounds(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  start_ts INTEGER NOT NULL,
  end_ts   INTEGER,
  block_hash TEXT,                     -- set when solved
  network_difficulty REAL,
  status TEXT NOT NULL DEFAULT 'open'  -- open|found|matured|paid
);

CREATE TABLE IF NOT EXISTS shares(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  round_id INTEGER NOT NULL,
  miner_id TEXT NOT NULL,
  ts INTEGER NOT NULL,
  difficulty REAL NOT NULL,            -- share difficulty
  valid INTEGER NOT NULL,              -- 1/0
  FOREIGN KEY(round_id) REFERENCES rounds(id)
);

CREATE TABLE IF NOT EXISTS balances(
  wallet TEXT PRIMARY KEY,
  sats INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS payouts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  txid TEXT,
  total_sats INTEGER NOT NULL,
  fee_sats INTEGER NOT NULL,
  status TEXT NOT NULL                 -- pending|sent|confirming|confirmed
);

CREATE TABLE IF NOT EXISTS payout_items(
  payout_id INTEGER NOT NULL,
  wallet TEXT NOT NULL,
  sats INTEGER NOT NULL,
  FOREIGN KEY(payout_id) REFERENCES payouts(id)
);
