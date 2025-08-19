import os, time, json, requests
from pathlib import Path
from dotenv import load_dotenv
from base58 import b58decode_check
from bech32 import bech32_decode, convertbits

load_dotenv("config/.env")
HOST = os.getenv("BITCOIN_RPC_HOST","127.0.0.1")
PORT = int(os.getenv("BITCOIN_RPC_PORT","8332"))
COOKIE_PATH = os.getenv("COOKIE_PATH","")
RPC_USER = os.getenv("RPC_USER","")
RPC_PASSWORD = os.getenv("RPC_PASSWORD","")
RPC_WALLET = os.getenv("RPC_WALLET","bitbombe")
HOT_ADDR = os.getenv("HOT_POOL_ADDRESS")
RUNTIME_JOB_JSON = os.getenv("RUNTIME_JOB_JSON","./runtime/current_job.json")
EX1_BYTES = int(os.getenv("EXTRANONCE1_BYTES","4"))
EX2_BYTES = int(os.getenv("EXTRANONCE2_BYTES","4"))

def rpc(method, params=None):
    if params is None: params=[]
    url = f"http://{HOST}:{PORT}/wallet/{RPC_WALLET}" if RPC_WALLET else f"http://{HOST}:{PORT}"
    headers={"content-type":"application/json"}
    auth=None
    if COOKIE_PATH and os.path.exists(COOKIE_PATH):
        u,p=open(COOKIE_PATH,'r').read().strip().split(':',1); auth=(u,p)
    elif RPC_USER: auth=(RPC_USER,RPC_PASSWORD)
    r=requests.post(url,headers=headers,auth=auth,data=json.dumps({"jsonrpc":"1.0","id":"dx","method":method,"params":params}),timeout=10)
    r.raise_for_status(); j=r.json()
    if j.get("error"): raise RuntimeError(j["error"])
    return j["result"]

def encode_varint(n:int)->bytes:
    if n<0xfd: return bytes([n])
    if n<=0xffff: return b"\xfd"+n.to_bytes(2,'little')
    if n<=0xffffffff: return b"\xfe"+n.to_bytes(4,'little')
    return b"\xff"+n.to_bytes(8,'little')

def address_to_script(address:str)->bytes:
    if address.startswith("bc1"):
        hrp,data=bech32_decode(address)
        if hrp!="bc" or data is None: raise ValueError("bad bech32")
        witver=data[0]; prog=bytes(convertbits(data[1:],5,8,False))
        if witver!=0 or len(prog) not in (20,32): raise ValueError("unsupported witness addr")
        # P2WPKH/P2WSH scriptPubKey
        return bytes([0]) + bytes([len(prog)]) + prog
    else:
        raw=b58decode_check(address)
        ver=raw[0]; h160=raw[1:]
        if ver!=0x00: raise ValueError("only p2pkh base58 supported")
        return b"\x76\xa9"+bytes([len(h160)])+h160+b"\x88\xac"

def ser_tx_in(prevout, scriptsig, sequence=0xffffffff):
    return prevout + encode_varint(len(scriptsig)) + scriptsig + sequence.to_bytes(4,'little')

def ser_tx_out(value_sat:int, script:bytes):
    return value_sat.to_bytes(8,'little') + encode_varint(len(script)) + script

def make_coinbase_nonsegwit(height:int, en1:bytes, en2_len:int, cb_value:int, pool_addr:str):
    # scriptSig: <BIP34 height> <len(en1)> <en1> <len(en2)>   (miner inserts en2 bytes later)
    def bip34_push(h):
        b=b""
        while True:
            b += bytes([h & 0xff]); h >>= 8
            if h==0: break
        if b[-1] & 0x80: b += b"\x00"
        return bytes([len(b)]) + b
    scriptsig = bip34_push(height) + bytes([len(en1)]) + en1 + bytes([en2_len])
    prevout = b"\x00"*32 + b"\xff\xff\xff\xff"
    vin = ser_tx_in(prevout, scriptsig, 0xffffffff)
    vout = ser_tx_out(cb_value, address_to_script(pool_addr))
    version=(2).to_bytes(4,'little'); locktime=(0).to_bytes(4,'little')
    tx = version + encode_varint(1) + vin + encode_varint(1) + vout + locktime
    # Split into coinb1 (up to scriptsig end) and coinb2 (from sequence onward)
    coinb1 = version + encode_varint(1) + prevout + encode_varint(len(scriptsig)) + scriptsig
    coinb2 = (0xffffffff).to_bytes(4,'little') + encode_varint(1) + vout + locktime
    return coinb1.hex(), coinb2.hex()

def fetch_template():
    return rpc("getblocktemplate", [{"rules":["segwit"]}])  # OK even if we mine empty blocks

def make_job(tpl: dict):
    height=tpl["height"]; prevhash=tpl["previousblockhash"]; nbits=tpl["bits"]; version=tpl["version"]
    ntime=int(tpl["curtime"]); cb_value=tpl["coinbasevalue"]
    en1=os.urandom(EX1_BYTES)
    coinb1,coinb2 = make_coinbase_nonsegwit(height, en1, EX2_BYTES, cb_value, HOT_ADDR)
    prevhash_le=bytes.fromhex(prevhash)[::-1].hex()
    return {
        "job_id": f"{prevhash[:8]}{int(time.time())}",
        "version": version,
        "version_hex": f"{version:08x}",
        "prevhash": prevhash,
        "prevhash_le": prevhash_le,
        "nbits_hex": nbits,
        "ntime": ntime,
        "coinb1": coinb1,
        "coinb2": coinb2,
        "merkle_branch": [],  # empty block (coinbase only)
        "network_difficulty": tpl.get("difficulty",1.0),
        "height": height
    }

def write_job(job:dict, path:str):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(job))

if __name__ == "__main__":
    t=fetch_template(); j=make_job(t); write_job(j, RUNTIME_JOB_JSON)
    print("Wrote job:", RUNTIME_JOB_JSON)
