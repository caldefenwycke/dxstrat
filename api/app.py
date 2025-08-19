from fastapi import FastAPI
from pathlib import Path
import os, json, requests

app = FastAPI()
ROOT = "/opt/darwinx"
LOGDIR = os.environ.get("LOGDIR", f"{ROOT}/logs")
RPCU = os.environ["RPC_USER"]; RPCP = os.environ["RPC_PASSWORD"]
RPCH = os.environ.get("BITCOIN_RPC_HOST","127.0.0.1")
RPCPORT = os.environ.get("BITCOIN_RPC_PORT","8332")
WALLET = os.environ.get("RPC_WALLET","")

def rpc(method, params=None, wallet=False):
    url = f"http://{RPCH}:{RPCPORT}"
    if wallet and WALLET: url += f"/wallet/{WALLET}"
    r = requests.post(url, auth=(RPCU, RPCP),
                      json={"jsonrpc":"1.0","id":"dx","method":method,"params":params or []}, timeout=5)
    r.raise_for_status(); return r.json()["result"]

@app.get("/api/summary")
def summary():
    info = rpc("getblockchaininfo")
    return {
      "height": info["blocks"],
      "chain": info["chain"],
      "hot_pool_address": os.environ.get("HOT_POOL_ADDRESS",""),
      "stratum": {"host": os.environ.get("STRATUM_PUBLIC_HOST","0.0.0.0"),
                  "port": int(os.environ.get("STRATUM_PUBLIC_PORT","3333"))}
    }

@app.get("/api/round")  # simple per-round share totals from logs
def round_info():
    p = Path(LOGDIR)
    rounds = sorted([d for d in p.iterdir() if d.is_dir() and d.name.isdigit()])
    if not rounds: return {"rounds":[]}
    last = rounds[-1]
    totals = {}
    for f in last.rglob("shares.log"):
        for ln in f.read_text().splitlines():
            parts = ln.split()
            user=None; diff=None
            for t in parts:
                if t.startswith("user="): user=t[5:]
                elif t.startswith("diff="):
                    try: diff=float(t[5:])
                    except: pass
            if user and diff:
                wallet=user.split(".",1)[0]
                totals[wallet]=totals.get(wallet,0.0)+diff
    return {"height": int(last.name), "shares": totals}
