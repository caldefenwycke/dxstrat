#!/usr/bin/env python3
import os, time, json, subprocess, requests
from pathlib import Path

ROOT="/opt/darwinx"
LOGDIR=os.environ.get("LOGDIR", f"{ROOT}/logs")
RPCU=os.environ["RPC_USER"]; RPCP=os.environ["RPC_PASSWORD"]
RPCH=os.environ.get("BITCOIN_RPC_HOST","127.0.0.1")
RPCPORT=os.environ.get("BITCOIN_RPC_PORT","8332")
WALLET=os.environ.get("RPC_WALLET","poolhot")
HOT=os.environ["HOT_POOL_ADDRESS"]
FEEADDR=os.environ.get("POOL_FEE_ADDRESS", HOT)
FEEPCT=float(os.environ.get("POOL_FEE_PCT","2"))
CONFREQ=int(os.environ.get("ROUND_CONFIRMATIONS","100"))

STATE=Path(f"{ROOT}/runtime/payout.state.json"); STATE.parent.mkdir(parents=True, exist_ok=True)
state={"paid":{}}; 
if STATE.exists(): state=json.loads(STATE.read_text())

def rpc(method, params=None, wallet=False):
    url = f"http://{RPCH}:{RPCPORT}"
    if wallet and WALLET: url += f"/wallet/{WALLET}"
    r = requests.post(url, auth=(RPCU, RPCP),
      json={"jsonrpc":"1.0","id":"p","method":method,"params":params or []}, timeout=10)
    r.raise_for_status(); return r.json()["result"]

def find_solved_blocks():
    out = subprocess.run(["bash","-lc", f"grep -hR \"Solved block\" {LOGDIR}/*/pool.log 2>/dev/null | tail -2000"], 
                         capture_output=True, text=True)
    blocks=[]
    for ln in out.stdout.splitlines():
        toks=ln.split(); h=None; bh=None
        for t in toks:
            if t.startswith("height="):
                try: h=int(t.split("=")[1])
                except: pass
            if len(t)==64 and all(c in '0123456789abcdef' for c in t.lower()):
                bh=t
        if h and bh: blocks.append((h,bh))
    return blocks

def collect_round_shares(height):
    totals={}
    for f in Path(LOGDIR, str(height)).rglob("shares.log"):
        for ln in f.read_text().splitlines():
            parts=ln.split(); user=None; d=None
            for t in parts:
                if t.startswith("user="): user=t[5:]
                elif t.startswith("diff="):
                    try: d=float(t[5:])
                    except: pass
            if user and d:
                wallet=user.split(".",1)[0]
                totals[wallet]=totals.get(wallet,0.0)+d
    return totals

def pay_round(height, blockhash):
    if str(height) in state["paid"]: return
    b = rpc("getblock", [blockhash])
    if b.get("confirmations",0) < CONFREQ: return

    coinbase = rpc("getblock", [blockhash, 2])["tx"][0]
    reward = sum(v["value"] for v in coinbase["vout"])  # BTC
    fee = round(reward * (FEEPCT/100.0), 8)
    pot = round(reward - fee, 8)

    shares = collect_round_shares(height)
    tot = sum(shares.values()) or 0.0
    if tot == 0.0:
        state["paid"][str(height)]={"block":blockhash,"note":"no shares"}
        STATE.write_text(json.dumps(state, indent=2)); return

    outs={}
    if fee>0: outs[FEEADDR]=fee
    for w, s in shares.items():
        amt = round(pot * (s/tot), 8)
        if amt>0: outs[w]=outs.get(w,0)+amt

    txid = rpc("sendmany", ["", outs, 1, f"round{height}", [], False, True], wallet=True)
    state["paid"][str(height)]={"block":blockhash,"txid":txid,"sum":outs}
    STATE.write_text(json.dumps(state, indent=2))
    print(f"Paid round {height}: {txid}", flush=True)

def main():
    while True:
        for h,b in find_solved_blocks():
            pay_round(h,b)
        time.sleep(30)

if __name__=="__main__": main()
