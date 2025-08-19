import os, json, time, requests, sqlite3, hashlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("config/.env")
HOST=os.getenv("BITCOIN_RPC_HOST","127.0.0.1")
PORT=int(os.getenv("BITCOIN_RPC_PORT","8332"))
COOKIE_PATH=os.getenv("COOKIE_PATH","")
RPC_USER=os.getenv("RPC_USER","")
RPC_PASSWORD=os.getenv("RPC_PASSWORD","")
RPC_WALLET=os.getenv("RPC_WALLET","bitbombe")
DB_PATH=os.getenv("DB_PATH","./pool.db")
RUNTIME_JOB_JSON=os.getenv("RUNTIME_JOB_JSON","./runtime/current_job.json")

def db():
    con=sqlite3.connect(DB_PATH); con.execute("PRAGMA journal_mode=WAL;"); return con

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

def encode_varint(n:int)->bytes:
    if n<0xfd: return bytes([n])
    if n<=0xffff: return b"\xfd"+n.to_bytes(2,'little')
    if n<=0xffffffff: return b"\xfe"+n.to_bytes(4,'little')
    return b"\xff"+n.to_bytes(8,'little')

def dbl_sha256(b:bytes)->bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def assemble_coinbase_hex(coinb1_hex:str, en2_hex:str, coinb2_hex:str)->bytes:
    return bytes.fromhex(coinb1_hex + en2_hex + coinb2_hex)

def assemble_block_hex(job:dict, cand:dict)->str:
    # coinbase tx (non-segwit), txid = dbl_sha256(tx) in hex (little-endian when building merkle)
    coinbase = assemble_coinbase_hex(cand["coinb1"], cand["en2_hex"], cand["coinb2"])
    coinbase_txid_le = dbl_sha256(coinbase)[::-1]  # txid LE for header merkle

    # Merkle root = only coinbase
    merkle_le = coinbase_txid_le

    version = job["version"].to_bytes(4,'little')
    prevhash_le = bytes.fromhex(job["prevhash_le"])
    ntime = int(cand["ntime"]).to_bytes(4,'little')
    nbits_le = bytes.fromhex(job["nbits_hex"])[::-1]
    nonce = int(cand["nonce"]).to_bytes(4,'little')

    header = version + prevhash_le + merkle_le + ntime + nbits_le + nonce
    block_hash_be = dbl_sha256(header)[::-1].hex()

    # Block = header + varint(txcount=1) + coinbase
    block = header + encode_varint(1) + coinbase
    return block.hex(), block_hash_be

def mark_round_found(block_hash:str):
    con=db(); cur=con.cursor()
    ts=int(time.time())
    cur.execute("UPDATE rounds SET block_hash=?, end_ts=?, status='found' WHERE status='open' AND block_hash IS NULL", (block_hash, ts))
    con.commit(); con.close()

def submit_if_candidate():
    cpath=Path("runtime/block_candidate.json")
    jpath=Path(RUNTIME_JOB_JSON)
    if not cpath.exists() or not jpath.exists(): return
    cand=json.loads(cpath.read_text()); job=json.loads(jpath.read_text())
    try:
        block_hex, h = assemble_block_hex(job, cand)
        rpc("submitblock", [block_hex])  # returns null on success
        mark_round_found(h)
        cpath.unlink(missing_ok=True)
        print("Submitted block:", h)
    except Exception as e:
        print("submit error:", e)
        # keep candidate for retry
