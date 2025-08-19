import os, time, json, sqlite3, requests
from dotenv import load_dotenv

load_dotenv("config/.env")
DB_PATH=os.getenv("DB_PATH","./pool.db")
HOST=os.getenv("BITCOIN_RPC_HOST","127.0.0.1")
PORT=int(os.getenv("BITCOIN_RPC_PORT","8332"))
COOKIE_PATH=os.getenv("COOKIE_PATH","")
RPC_USER=os.getenv("RPC_USER","")
RPC_PASSWORD=os.getenv("RPC_PASSWORD","")
RPC_WALLET=os.getenv("RPC_WALLET","bitbombe")
POOL_FEE_BPS=int(os.getenv("POOL_FEE_BASIS_POINTS","200"))
MIN_PAYOUT=int(os.getenv("MIN_PAYOUT_SATS","50000"))
BLOCK_MATURITY=int(os.getenv("BLOCK_MATURITY","100"))
PAYOUT_INTERVAL=int(os.getenv("PAYOUT_INTERVAL_SEC","600"))

def rpc(method, params=None):
    if params is None: params=[]
    url=f"http://{HOST}:{PORT}/wallet/{RPC_WALLET}" if RPC_WALLET else f"http://{HOST}:{PORT}"
    headers={"content-type":"application/json"}
    auth=None
    if COOKIE_PATH and os.path.exists(COOKIE_PATH):
        u,p=open(COOKIE_PATH,'r').read().strip().split(':',1); auth=(u,p)
    elif RPC_USER: auth=(RPC_USER,RPC_PASSWORD)
    r=requests.post(url,headers=headers,auth=auth,data=json.dumps({"jsonrpc":"1.0","id":"dx","method":method,"params":params}),timeout=15)
    r.raise_for_status(); j=r.json()
    if j.get("error"): raise RuntimeError(j["error"])
    return j["result"]

def matured_rounds():
    con=sqlite3.connect(DB_PATH); cur=con.cursor()
    rows=cur.execute("SELECT id, block_hash FROM rounds WHERE status='found' AND block_hash IS NOT NULL").fetchall()
    out=[]
    for (rid, bh) in rows:
        try:
            hdr=rpc("getblockheader",[bh])
            if hdr.get("confirmations",0) >= BLOCK_MATURITY:
                out.append((rid,bh,hdr.get("height")))
        except: pass
    con.close(); return out

def block_subsidy(height:int)->int:
    # ask node (since rules may change): use getblocksubsidy if available; fallback = 6.25 BTC era approx via node RPC
    try:
        s=rpc("getblocksubsidy", [height])
        return int(s["miner"])  # satoshis
    except:
        # Very rough fallback: 6.25 BTC in sats
        return int(6.25 * 100_000_000)

def pay_round(rid:int, block_hash:str, height:int):
    con=sqlite3.connect(DB_PATH); cur=con.cursor()
    shares=cur.execute("SELECT miner_id, SUM(difficulty) FROM shares WHERE round_id=? AND valid=1 GROUP BY miner_id", (rid,)).fetchall()
    if not shares:
        # nothing to pay, still mark matured->paid to avoid loop
        cur.execute("UPDATE rounds SET status='paid' WHERE id=?", (rid,)); con.commit(); con.close(); return "no-shares"

    total_diff=sum(v for _,v in shares)
    # reward: subsidy only (empty blocks). If you later include tx fees, add here.
    reward_sats = block_subsidy(height)
    net_sats = int(reward_sats * (1 - POOL_FEE_BPS/10000))

    # build recipients
    # miner_id = wallet.worker -> split to wallet
    amounts={}
    for mid, diffsum in shares:
        wallet=mid.split(".",1)[0]
        portion = diffsum/total_diff if total_diff>0 else 0
        sats = int(net_sats * portion)
        if sats >= MIN_PAYOUT:
            amounts[wallet] = amounts.get(wallet,0) + sats

    if not amounts:
        # accumulate threshold not met: mark paid and skip; (or write balances logic if you want carry-over)
        cur.execute("UPDATE rounds SET status='paid' WHERE id=?", (rid,))
        con.commit(); con.close(); return "below-min"

    # sendmany expects BTC amounts
    recipients={w: (s/100_000_000) for w,s in amounts.items()}
    try:
        txid = rpc("sendmany", ["", recipients, 1, f"Round {rid} payout", [], True])
        # record payout
        cur.execute("INSERT INTO payouts(round_id,ts,txid,total_sats,fee_sats,status) VALUES(?,?,?,?,?,?)",
                    (rid, int(time.time()), txid, sum(amounts.values()), reward_sats-net_sats, "sent"))
        cur.execute("UPDATE rounds SET status='paid' WHERE id=?", (rid,))
        con.commit(); con.close()
        return txid
    except Exception as e:
        cur.execute("INSERT INTO payouts(round_id,ts,txid,total_sats,fee_sats,status) VALUES(?,?,?,?,?,?)",
                    (rid, int(time.time()), str(e), sum(amounts.values()), reward_sats-net_sats, "error"))
        con.commit(); con.close()
        return f"error: {e}"

def main_loop():
    while True:
        try:
            # mark 'found' rounds as 'matured' when confirmations reached
            for rid,bh,h in matured_rounds():
                # immediately pay matured round
                pay_round(rid, bh, h)
            time.sleep(PAYOUT_INTERVAL)
        except Exception as e:
            print("payout error:", e); time.sleep(30)

if __name__=="__main__": main_loop()
