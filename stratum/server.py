import asyncio, json, os, time, hashlib, sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("config/.env")
STRATUM_HOST = os.getenv("STRATUM_HOST","0.0.0.0")
STRATUM_PORT = int(os.getenv("STRATUM_PORT","3333"))
EXTRANONCE1_BYTES = int(os.getenv("EXTRANONCE1_BYTES","4"))
EXTRANONCE2_BYTES = int(os.getenv("EXTRANONCE2_BYTES","4"))
VARDIFF_TARGET = int(os.getenv("VARDIFF_TARGET","15"))
DIFF_MIN = float(os.getenv("DIFF_MIN","1"))
DIFF_MAX = float(os.getenv("DIFF_MAX","131072"))
DB_PATH = os.getenv("DB_PATH","./pool.db")
RUNTIME_JOB_JSON = os.getenv("RUNTIME_JOB_JSON","./runtime/current_job.json")

DIFF1_TARGET_INT = int("00000000FFFF0000000000000000000000000000000000000000000000000000", 16)

def db_connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    return con

def db_init():
    con = db_connect()
    with open("db/schema.sql","r",encoding="utf-8") as f:
        con.executescript(f.read())
    con.commit(); con.close()

def target_from_diff(diff: float) -> int:
    if diff <= 0: diff = 1.0
    t = int(DIFF1_TARGET_INT / diff)
    return max(1, t)

def int_le(n, length): return n.to_bytes(length,'little')
def dbl_sha256(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

class JobState:
    def __init__(self, path): self.path=Path(path); self.cur=None; self.mtime=0.0
    def load_if_changed(self):
        if not self.path.exists(): return None
        mt=self.path.stat().st_mtime
        if mt<=self.mtime: return None
        self.mtime=mt
        self.cur=json.loads(self.path.read_text()); return self.cur
    def get(self): return self.cur

job_state = JobState(RUNTIME_JOB_JSON)

class Miner:
    def __init__(self, reader, writer, server):
        self.reader=reader; self.writer=writer; self.server=server
        self.id=None; self.wallet=None; self.worker=None; self.authorized=False
        self.extra_nonce1=os.urandom(EXTRANONCE1_BYTES).hex()
        self.diff=max(DIFF_MIN,1.0); self.last_submit_times=[]
        self.conn_ts=time.time()

    async def send(self,obj): 
        self.writer.write((json.dumps(obj)+"\n").encode()); await self.writer.drain()

    async def handle(self):
        while True:
            line = await self.reader.readline()
            if not line: self.server.on_disconnect(self); break
            try: req=json.loads(line.decode().strip())
            except: continue
            asyncio.create_task(self.dispatch(req))

    async def dispatch(self, req):
        mid=req.get("id"); method=req.get("method"); params=req.get("params",[])
        if method=="mining.subscribe":
            result=[["mining.set_difficulty","mining.notify"], self.extra_nonce1, EXTRANONCE2_BYTES]
            await self.send({"id":mid,"result":result,"error":None})
            await self.set_difficulty(self.diff)
            await self.notify_current_job(clean=True); return
        if method=="mining.authorize":
            try:
                username=params[0]
                parts=username.split(".",1)
                if len(parts)!=2: raise ValueError
                wallet,worker=parts
                if not (wallet.startswith("bc1") or 26<=len(wallet)<=62): raise ValueError
                self.id=username; self.wallet=wallet; self.worker=worker; self.authorized=True
                self.server.on_authorize(self)
                await self.send({"id":mid,"result":True,"error":None}); return
            except:
                await self.send({"id":mid,"result":False,"error":[24,"Unauthorized",None]}); return
        if method=="mining.submit":
            try:
                _, job_id, en2_hex, ntime_hex, nonce_hex = params
                await self.handle_submit(job_id, en2_hex, ntime_hex, nonce_hex, mid)
            except:
                await self.send({"id":mid,"result":False,"error":[23,"Invalid submit",None]})
            return
        if method=="mining.extranonce.subscribe":
            await self.send({"id":mid,"result":True,"error":None}); return
        await self.send({"id":mid,"result":None,"error":[20,"Unknown method",None]})

    async def set_difficulty(self, d):
        self.diff=max(DIFF_MIN,min(DIFF_MAX,float(d)))
        await self.send({"id":None,"method":"mining.set_difficulty","params":[self.diff]})

    async def notify_current_job(self, clean=False):
        job=job_state.get()
        if not job: return
        params=[ job["job_id"], job["prevhash_le"], job["coinb1"], job["coinb2"],
                 job["merkle_branch"], job["version_hex"], job["nbits_hex"], f'{job["ntime"]:08x}', bool(clean) ]
        await self.send({"id":None,"method":"mining.notify","params":params})

    async def handle_submit(self, job_id, en2_hex, ntime_hex, nonce_hex, mid):
        job=job_state.get()
        if not job or job["job_id"]!=job_id:
            await self.send({"id":mid,"result":False,"error":[21,"Stale job",None]}); return

        # Build coinbase (non-witness) for txid/merkle
        coinb = bytes.fromhex(job["coinb1"] + en2_hex + job["coinb2"])

        coinbase_hash = dbl_sha256(coinb)
        mr = coinbase_hash
        for b in job["merkle_branch"]:
            mr = dbl_sha256(mr + bytes.fromhex(b))
        merkle_hex_le = mr[::-1].hex()

        version = job["version"]
        prevhash_le = job["prevhash_le"]
        ntime = int(ntime_hex,16)
        nbits_le = bytes.fromhex(job["nbits_hex"])[::-1]     # little-endian in header
        nonce = int(nonce_hex,16)

        header = (
            version.to_bytes(4,'little') +
            bytes.fromhex(prevhash_le) +
            bytes.fromhex(merkle_hex_le) +
            ntime.to_bytes(4,'little') +
            nbits_le +
            nonce.to_bytes(4,'little')
        )
        h = dbl_sha256(header); h_int = int.from_bytes(h[::-1],'big')

        share_target = target_from_diff(self.diff)
        # network target from nbits:
        def bits_to_target(bits_hex):
            bits = bytes.fromhex(bits_hex)
            exp = bits[0]; mant = int.from_bytes(bits[1:],'big')
            return mant * (1 << (8*(exp-3)))
        block_target = bits_to_target(job["nbits_hex"])

        valid_share = h_int <= share_target
        valid_block = h_int <= block_target

        self.server.on_share(self, valid_share)

        if valid_block:
            self.server.on_block_candidate(job, en2_hex, ntime, nonce, merkle_hex_le, header[::-1].hex())

        await self.send({"id":mid,"result":bool(valid_share),"error":None})

        # crude vardiff tuning to target VARDIFF_TARGET shares/min
        now=time.time()
        self.last_submit_times=[t for t in self.last_submit_times if t>now-60]
        self.last_submit_times.append(now)
        rate=len(self.last_submit_times)/60.0
        if rate>(VARDIFF_TARGET*1.5)/60: await self.set_difficulty(self.diff*2.0)
        elif rate<(VARDIFF_TARGET*0.5)/60 and self.diff>DIFF_MIN: await self.set_difficulty(max(DIFF_MIN,self.diff/2.0))

class StratumServer:
    def __init__(self):
        self.con=db_connect(); self.cur=self.con.cursor(); self.clients={}

    def on_authorize(self, miner: Miner):
        ts=int(time.time())
        self.cur.execute("""INSERT INTO miners(id,wallet,worker,first_seen_ts,last_seen_ts,vardiff)
                            VALUES(?,?,?,?,?,?)
                            ON CONFLICT(id) DO UPDATE SET last_seen_ts=excluded.last_seen_ts""",
                         (miner.id, miner.wallet, miner.worker, ts, ts, miner.diff))
        self.con.commit(); self.clients[miner.id]=miner

    def on_disconnect(self, miner: Miner): self.clients.pop(miner.id,None)

    def get_open_round_id(self):
        r=self.cur.execute("SELECT id FROM rounds WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
        if r: return r[0]
        ts=int(time.time()); self.cur.execute("INSERT INTO rounds(start_ts,status) VALUES(?,?)",(ts,"open"))
        self.con.commit(); return self.cur.lastrowid

    def on_share(self, miner: Miner, valid: bool):
        ts=int(time.time()); rid=self.get_open_round_id()
        self.cur.execute("INSERT INTO shares(round_id,miner_id,ts,difficulty,valid) VALUES(?,?,?,?,?)",
                         (rid, miner.id, ts, miner.diff, 1 if valid else 0))
        if valid:
            self.cur.execute("UPDATE miners SET total_accepted=total_accepted+1,last_seen_ts=? WHERE id=?",(ts,miner.id))
        else:
            self.cur.execute("UPDATE miners SET total_rejected=total_rejected+1,last_seen_ts=? WHERE id=?",(ts,miner.id))
        self.con.commit()

    def on_block_candidate(self, job, en2_hex, ntime, nonce, merkle_hex_le, blockhash_be_hex):
        # mark round end; write candidate for engine to build+submit
        ts=int(time.time())
        self.cur.execute("UPDATE rounds SET end_ts=? WHERE status='open'", (ts,))
        self.con.commit()
        Path("runtime").mkdir(parents=True,exist_ok=True)
        Path("runtime/block_candidate.json").write_text(json.dumps({
            "job_id": job["job_id"],
            "version": job["version"],
            "prevhash": job["prevhash"],
            "nbits_hex": job["nbits_hex"],
            "ntime": ntime,
            "nonce": nonce,
            "coinb1": job["coinb1"],
            "coinb2": job["coinb2"],
            "en2_hex": en2_hex
        }))

    async def notify_loop(self):
        while True:
            changed=job_state.load_if_changed()
            if changed:
                try:
                    self.cur.execute("UPDATE rounds SET prevhash=?, network_difficulty=? WHERE status='open'",
                                     (changed["prevhash"], changed["network_difficulty"]))
                    self.con.commit()
                except: pass
                for m in list(self.clients.values()):
                    try: await m.notify_current_job(clean=True)
                    except: pass
            await asyncio.sleep(1)

    async def client(self, r, w):
        m=Miner(r,w,self)
        try: await m.handle()
        finally:
            w.close(); await w.wait_closed()

    async def run(self):
        server = await asyncio.start_server(self.client, STRATUM_HOST, STRATUM_PORT)
        async with server:
            await asyncio.gather(server.serve_forever(), self.notify_loop())

def main():
    db_init(); Path("runtime").mkdir(parents=True,exist_ok=True)
    asyncio.run(StratumServer().run())

if __name__=="__main__": main()
