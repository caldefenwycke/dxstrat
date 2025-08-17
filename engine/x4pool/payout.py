#!/usr/bin/env python3
import os, time, sqlite3
from decimal import Decimal, getcontext
from dotenv import load_dotenv
from src.dxstrat.db import DB_PATH
from src.dxstrat.rpc import getblockheader, sendmany, getaddressinfo

load_dotenv()
getcontext().prec = 18

POOL_FEE_BP = int(os.getenv("POOL_FEE_BP","200"))      # 2%
MATURITY     = int(os.getenv("COINBASE_MATURITY","100"))
FALLBACK_HRS = int(os.getenv("PPLNS_FALLBACK_HOURS","24"))

def sats_to_btc(sats: int) -> str:
    return str(Decimal(sats) / Decimal(1e8))

def prev_round_start_ts(con, this_ts: int):
    row = con.execute("SELECT ts FROM blocks WHERE ts < ? ORDER BY ts DESC LIMIT 1", (this_ts,)).fetchone()
    return row[0] if row else this_ts - FALLBACK_HRS*3600

def gather_shares(con, start_ts: int, end_ts: int):
    rows = con.execute("""
      SELECT worker, SUM(diff) as w FROM shares
      WHERE accepted_ts >= ? AND accepted_ts <= ?
      GROUP BY worker
    """, (start_ts, end_ts)).fetchall()
    return {r[0]: (r[1] or 0.0) for r in rows}

def mature_blocks(con):
    rows = con.execute("SELECT id, bhash, height, reward_sats, ts, matured, paid FROM blocks WHERE paid=0").fetchall()
    out = []
    for (bid, bh, h, rew, ts, matured, paid) in rows:
        try:
            hdr = getblockheader(bh); confs = int(hdr.get("confirmations", 0))
        except Exception:
            confs = 0
        out.append((bid, bh, h, rew, ts, confs))
    return out

def mark_matured(con, bid): con.execute("UPDATE blocks SET matured=1 WHERE id=?", (bid,))
def mark_paid(con, bid):    con.execute("UPDATE blocks SET paid=1 WHERE id=?", (bid,))

def extract_addr(worker: str) -> str:
    token = worker.split(".")[0]
    try:
        info = getaddressinfo(token)
        if info.get("isvalid", False): return token
    except Exception: pass
    return ""

def main():
    with sqlite3.connect(DB_PATH) as con:
        for (bid, bh, height, reward_sats, ts_block, confs) in mature_blocks(con):
            if confs < MATURITY: continue

            start_ts = prev_round_start_ts(con, ts_block)
            shares = gather_shares(con, start_ts, ts_block)
            total = sum(shares.values())
            if total <= 0:
                mark_matured(con, bid); mark_paid(con, bid)
                print(f"[PAYOUT] No shares for block {bh[:16]}.. -> paid")
                continue

            pool_fee = int(reward_sats * POOL_FEE_BP / 10000)
            distributable = reward_sats - pool_fee

            payments_btc = {}
            for worker, w in shares.items():
                portion = Decimal(w) / Decimal(total)
                amt_sats = int(Decimal(distributable) * portion)
                if amt_sats <= 0: continue
                addr = extract_addr(worker)
                if not addr: continue
                payments_btc[addr] = sats_to_btc(amt_sats)

            if not payments_btc:
                mark_matured(con, bid); mark_paid(con, bid)
                print(f"[PAYOUT] No valid recipients for block {bh[:16]}.. -> paid")
                continue

            try:
                txid = sendmany(payments_btc)
                mark_matured(con, bid); mark_paid(con, bid)
                print(f"[PAYOUT] Block {bh[:16]}.. paid tx {txid}")
            except Exception as e:
                print(f"[PAYOUT] sendmany error: {e}")

if __name__ == "__main__":
    main()
