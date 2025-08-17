import asyncio, json, os, time, uvloop
from typing import Dict, Tuple, Set
from dotenv import load_dotenv
load_dotenv()

from .jobmaker import X4JobMaker
from .utils import target_from_nbits, target_from_difficulty, dblsha, hash_to_int, u32le, varint, txid_from_tx_hex
from .db import upsert_miner, insert_share, insert_block, init as db_init
from .rpc import submitblock, getaddressinfo

HOST = os.getenv("STRATUM_HOST","0.0.0.0")
PORT = int(os.getenv("STRATUM_PORT","3333"))
EX1_SIZE = int(os.getenv("EXTRANONCE1_SIZE","4"))
EX2_SIZE = int(os.getenv("EXTRANONCE2_SIZE","4"))

def extract_address(token: str) -> str:
    cand = token.split(".")[0].split("/")[0].split(":")[0]
    try:
        info = getaddressinfo(cand)
        if info.get("isvalid"): return cand
    except Exception: pass
    return ""

class StratumServer:
    def __init__(self):
        db_init()
        self.jobs = X4JobMaker()
        self.clients: Set["Client"] = set()
        self.active_jobs: Dict[str, Dict] = {}
        self.seen_shares: Set[Tuple[str,str,str]] = set()

    async def start(self):
        srv = await asyncio.start_server(self.accept, HOST, PORT)
        addrs = ", ".join(str(sock.getsockname()) for sock in srv.sockets)
        print(f"[x4] listening on {addrs}")
        async with srv:
            await srv.serve_forever()

    async def accept(self, r, w):
        c = Client(r, w, self)
        self.clients.add(c)
        try:
            await c.handle()
        finally:
            self.clients.discard(c)

class Client:
    def __init__(self, reader, writer, server: StratumServer):
        self.r = reader; self.w = writer; self.server = server
        self.subscribed = False; self.authorized = False
        self.addr = writer.get_extra_info("peername")
        self.username = "unknown"
        self.extranonce1 = os.urandom(EX1_SIZE).hex()
        self.diff = 2048.0
        self.current_job = None
        self.payout_addr = ""

    async def send(self, obj):
        self.w.write((json.dumps(obj) + "\n").encode())
        await self.w.drain()

    async def handle(self):
        try:
            while True:
                line = await self.r.readline()
                if not line: break
                try:
                    msg = json.loads(line.decode().strip())
                except Exception:
                    continue
                method = msg.get("method"); _id = msg.get("id")
                params = msg.get("params", [])
                if method == "mining.subscribe":
                    self.subscribed = True
                    res = [["mining.set_difficulty","mining.notify"], self.extranonce1, EX2_SIZE]
                    await self.send({"id": _id, "result": res, "error": None})
                    await self.set_difficulty(self.diff)
                    await self.push_job(clean=True)
                elif method == "mining.authorize":
                    self.username = params[0] if params else "unknown"
                    self.authorized = True
                    upsert_miner(self.username)
                    self.payout_addr = extract_address(self.username)
                    await self.send({"id": _id, "result": True, "error": None})
                elif method == "mining.submit":
                    ok = await self.handle_submit(params)
                    await self.send({"id": _id, "result": ok, "error": None if ok else True})
                    await self.push_job(clean=False)
                else:
                    await self.send({"id": _id, "result": True, "error": None})
        except Exception:
            pass
        finally:
            self.w.close()
            await self.w.wait_closed()

    async def set_difficulty(self, d: float):
        self.diff = float(d)
        await self.send({"id": None, "method": "mining.set_difficulty", "params": [self.diff]})

    async def push_job(self, clean: bool):
        job = self.server.jobs.make_job()
        self.server.active_jobs[job["job_id"]] = job
        self.current_job = job
        params = [
            job["job_id"],
            job["prevhash_be"],
            job["coinb1"],
            job["coinb2"],
            job["merkle_branch"],
            f"{job['version']:08x}",
            job["nbits"],
            f"{job['ntime']:08x}",
            True if clean else False
        ]
        await self.send({"id": None, "method": "mining.notify", "params": params})

    def build_header_and_block(self, job: Dict, ex2_hex: str, ntime_hex: str, nonce_hex: str):
        # coinbase = coinb1 + extranonce1 + extranonce2 + coinb2
        coinbase_hex = job["coinb1"] + self.extranonce1 + ex2_hex + job["coinb2"]
        cb_txid = txid_from_tx_hex(coinbase_hex)  # BE hex

        # merkle root from branch
        mr = bytes.fromhex(cb_txid)[::-1]
        for sib_be in job["merkle_branch"]:
            mr = dblsha(mr + bytes.fromhex(sib_be)[::-1])
        merkle_root_le = mr.hex()

        header = (
            u32le(job["version"]) +
            bytes.fromhex(job["prevhash_be"])[::-1] +
            bytes.fromhex(merkle_root_le) +
            bytes.fromhex(ntime_hex) +
            bytes.fromhex(job["nbits"]) +
            bytes.fromhex(nonce_hex)
        )
        share_target = target_from_difficulty(self.diff)
        block_hex = ""
        net_target = target_from_nbits(job["nbits"])
        hv = hash_to_int(dblsha(header))
        if hv <= net_target:
            txs = [coinbase_hex] + [tx["data"] for tx in job["tmpl"].get("transactions", [])]
            block_hex = header.hex() + varint(len(txs)).hex() + "".join(txs)
        return header, share_target, block_hex

    async def handle_submit(self, params) -> bool:
        try:
            _worker, job_id, ex2_hex, ntime_hex, nonce_hex = params[:5]
        except Exception:
            return False
        dup_key = (self.username, job_id, nonce_hex)
        if dup_key in self.server.seen_shares: return False
        self.server.seen_shares.add(dup_key)

        job = self.server.active_jobs.get(job_id)
        if not job: return False

        try:
            ntime = int(ntime_hex, 16)
            now = int(time.time())
            if ntime < now - 2*3600 or ntime > now + 2*3600: return False
        except Exception:
            return False

        header, share_target, block_hex = self.build_header_and_block(job, ex2_hex, ntime_hex, nonce_hex)
        hv = hash_to_int(dblsha(header))
        if hv > share_target: return False

        # accepted share
        try: insert_share(self.username, job_id, float(self.diff))
        except Exception as e: print(f"[DB] share insert error: {e}")

        # solved block?
        if block_hex:
            try:
                res = submitblock(block_hex)
            except Exception as e:
                res = f"error: {e}"
            bhash = dblsha(header)[::-1].hex()
            reward_sats = int(job["tmpl"]["coinbasevalue"])
            try:
                insert_block(job["height"], bhash, reward_sats, self.username)
                print(f"[BLOCK] height={job['height']} hash={bhash} reward={reward_sats} sats submit={res}")
            except Exception as e:
                print(f"[DB] block insert error: {e}")
        return True

def main():
    uvloop.install()
    ss = StratumServer()
    asyncio.run(ss.start())

if __name__ == "__main__":
    main()
