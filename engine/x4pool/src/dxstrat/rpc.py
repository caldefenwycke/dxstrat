import base64, json, time, http.client, os
from dotenv import load_dotenv
load_dotenv()

HOST = os.getenv("BITCOIN_RPC_HOST","127.0.0.1")
PORT = int(os.getenv("BITCOIN_RPC_PORT","8332"))
USER = os.getenv("BITCOIN_RPC_USER","")
PW   = os.getenv("BITCOIN_RPC_PASS","")

def _rpc(method, params=None, timeout=30):
    if params is None: params = []
    auth = f"{USER}:{PW}".encode()
    headers = {
        "Authorization": "Basic " + base64.b64encode(auth).decode(),
        "Content-Type": "application/json"
    }
    body = json.dumps({"jsonrpc":"2.0","id":int(time.time()*1000),"method":method,"params":params})
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    conn.request("POST", "/", body, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    if resp.status != 200:
        raise RuntimeError(f"RPC HTTP {resp.status}: {data[:200]}")
    out = json.loads(data)
    if out.get("error"):
        raise RuntimeError(out["error"])
    return out["result"]

def getblocktemplate():
    return _rpc("getblocktemplate", [{ "rules": ["segwit"] }])

def submitblock(block_hex: str):
    return _rpc("submitblock", [block_hex])

def getaddressinfo(addr: str):
    return _rpc("getaddressinfo", [addr])

def getblockheader(block_hash: str):
    return _rpc("getblockheader", [block_hash, True])

def sendmany(payments: dict):
    # values must be BTC amounts (string or float)
    return _rpc("sendmany", ["", payments])
