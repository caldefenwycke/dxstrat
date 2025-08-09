import asyncio, json, time, sqlite3, os

from engine.pool import DarwinXEngine
from engine.coinbase import dsha256, varint
from engine.rpc import Rpc

CONFIG_PATH='config/config.json'; DB_PATH='db/pool.db'

def target_from_nbits(nbits_hex: str)->int:
    n=int(nbits_hex,16); exp=n>>24; mant=n & 0xffffff; return mant*(1<<(8*(exp-3)))

def assemble_block(job, ntime_hex, nonce_hex):
    version = bytes.fromhex(job['version'])
    prev = bytes.fromhex(job['prevhash'])[::-1]
    merkle = bytes.fromhex(job['merkle_root'])[::-1]
    ntime = int(ntime_hex, 16).to_bytes(4, 'little')
    nbits = bytes.fromhex(job['nbits'])[::-1]
    nonce = int(nonce_hex, 16).to_bytes(4, 'little')

    header = b''.join([version, prev, merkle, ntime, nbits, nonce])
    # Build block body: varint tx count + all transactions (coinbase first)
    coinbase = bytes.fromhex(job['coinbase_tx'])
    txs = [coinbase] + [bytes.fromhex(x) for x in job.get('txs',[])]
    body = varint(len(txs)) + b''.join(txs)
    block = header + body
    return block

class VarDiff:
    def __init__(self,c): v=c['vardiff']; self.initial=v['initial_difficulty']; self.tspm=60.0/v['target_seconds_per_share']; self.win=v['adjust_every_seconds']; self.min=v['min_difficulty']; self.max=v['max_difficulty']; self.r=v['adjust_ratio']
    def adjust(self,cur,shares): 
        if shares==0: return max(cur*(1.0-self.r), self.min)
        delta=shares-self.tspm
        if abs(delta)<0.5: return cur
        nd=cur*(1.0+self.r) if shares>self.tspm else cur*(1.0-self.r)
        return max(self.min, min(self.max, nd))

class StratumServer:
    def __init__(self,cfg):
        self.cfg=cfg; self.engine=DarwinXEngine(cfg); r=cfg['rpc']; self.rpc=Rpc(r['host'],r['port'],r['user'],r['password']); self.port=cfg['pool']['stratum_port']
        self.db=sqlite3.connect(DB_PATH, check_same_thread=False); self.db.row_factory=sqlite3.Row
        self.vardiff=VarDiff(cfg); self.ex1=os.urandom(4).hex(); self.ex2_size=8
        # Ensure stats tables
        self.q("""CREATE TABLE IF NOT EXISTS engine_stats (
            id INTEGER PRIMARY KEY CHECK (id=1),
            template_prevhash TEXT,
            template_height INTEGER,
            started_ts INTEGER,
            pool_size_current INTEGER,
            generated_since_template INTEGER,
            top_score REAL,
            top_hash_norm REAL,
            top_entropy REAL,
            w_hash REAL,
            w_ent REAL,
            last_update INTEGER,
            top_list TEXT
        )""")
        # Try ensure top_list column exists (SQLite lacks IF NOT EXISTS for columns)
        try:
            self.q("ALTER TABLE engine_stats ADD COLUMN top_list TEXT")
        except Exception:
            pass
        self.q("CREATE TABLE IF NOT EXISTS engine_stats_series (ts INTEGER, generated_since_template INTEGER)")

    async def start(self):
        import threading; threading.Thread(target=self.engine.loop, daemon=True).start()
        server=await asyncio.start_server(self.handle, '0.0.0.0', self.port); print(f"[STRATUM] 0.0.0.0:{self.port}");
        asyncio.create_task(self._stats_task())
        async with server:
            await server.serve_forever()
    def q(self,sql,p=()): cur=self.db.cursor(); cur.execute(sql,p); self.db.commit(); return cur

    async def handle(self, reader, writer):
        miner_id=None; diff=self.vardiff.initial; window=[]; last=int(time.time()); job=None

        async def send(obj): writer.write((json.dumps(obj)+'\n').encode()); await writer.drain()
        async def notify(job):
            await send({"id":None,"method":"mining.notify","params":[job['job_id'],job['prevhash'],"","",[],job['version'],job['nbits'],job['ntime'],True]})

        try:
            await send({"id":1,"result":[True,self.ex1,self.ex2_size],"error":None})
            msg=json.loads((await reader.readline()).decode())
            if msg.get('method')!='mining.authorize': writer.close(); await writer.wait_closed(); return
            username,_pw=msg['params']; address=username.split('.',1)[0]; now=int(time.time())
            self.q("""INSERT INTO miners(id,address,first_seen_ts,last_seen_ts,difficulty) VALUES(?,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET last_seen_ts=excluded.last_seen_ts""",(username,address,now,now,diff))
            await send({"id":msg.get('id'),"result":True,"error":None})

            job=self.engine.lease_best_job()
            if job:
                # Persist job for audit/assembly
                self.q("""INSERT OR REPLACE INTO jobs(id, miner_id, created_ts, prevhash, version, nbits, ntime, merkle_root, clean_jobs, exclusive, used)
                          VALUES(?,?,?,?,?,?,?,?,?,?,0)""",
                       (job['job_id'], username, int(time.time()), job['prevhash'], job['version'], job['nbits'], job['ntime'], job['merkle_root'], 1, 1))
                # store coinbase/txs in a side table (or pack into JSON in jobs if desired); here we use a simple file cache
                # For simplicity in this environment, attach the job dict to the connection:
                current_job = job
                await notify(job)

            while not reader.at_eof():
                line=await reader.readline()
                if not line: break
                m=json.loads(line.decode())

                if m.get('method') == 'mining.submit':
                    _w, jid, ex2, ntime_hex, nonce_hex = m['params'][:5]
                    if not job or jid != job['job_id']:
                        # Ignore stale submit
                        await send({"id": m.get('id'), "result": False, "error": None})
                        continue
                    net_target=target_from_nbits(job['nbits']); max_target=(1<<256)-1; share_target=int(max_target/diff)
                    version=bytes.fromhex(job['version']); prev=bytes.fromhex(job['prevhash'])[::-1]; merkle=bytes.fromhex(job['merkle_root'])[::-1]
                    ntime=int(ntime_hex,16).to_bytes(4,'little'); nbits=bytes.fromhex(job['nbits'])[::-1]; nonce=int(nonce_hex,16).to_bytes(4,'little')
                    hdr=b''.join([version,prev,merkle,ntime,nbits,nonce]); hv=int.from_bytes(dsha256(hdr),'big')
                    valid = hv < share_target; found = hv < net_target
                    self.q("INSERT INTO shares(miner_id,received_ts,difficulty,valid,pow_hash) VALUES(?,?,?,?,?)",(username,int(time.time()),diff,1 if valid else 0,hex(hv)[2:]))
                    if valid:
                        block_reward=int(job.get('reward_sats', 0))
                        network_diff=max_target/net_target
                        credit=int((diff / network_diff)*block_reward*(1.0 - self.cfg['pool']['pool_fee_percent']/100.0))
                        self.q("UPDATE miners SET total_accepted=total_accepted+1, balance_sats=balance_sats+? WHERE id=?", (max(0,credit), username))
                        await send({"id":m.get('id'),"result":True,"error":None})
                    else:
                        self.q("UPDATE miners SET total_rejected=total_rejected+1 WHERE id=?", (username,))
                        await send({"id":m.get('id'),"result":False,"error":None})

                    if found:
                        # Assemble full block and submit via RPC
                        block = assemble_block(job, ntime_hex, nonce_hex)
                        hex_block = block.hex()
                        try:
                            res = self.rpc.submitblock(hex_block)
                            self.q("INSERT INTO blocks(height,hash,found_ts,status,template_prevhash,reward_sats) VALUES(?, ?, ?, ?, ?, ?)", 
                                   (job.get('height'), None, int(time.time()), 'submitted', job['prevhash'], int(job.get('reward_sats',0))))
                        except Exception as e:
                            self.q("INSERT INTO blocks(height,hash,found_ts,status,template_prevhash,reward_sats) VALUES(?, ?, ?, ?, ?, ?)", 
                                   (job.get('height'), None, int(time.time()), f'error:{e}', job['prevhash'], int(job.get('reward_sats',0))))

                    # vardiff tick
                    now=int(time.time()); window=[t for t in window if now-t<self.vardiff.win]; window.append(now)
                    if now-last>=self.vardiff.win:
                        diff=self.vardiff.adjust(diff, len(window)); last=now; window.clear()
                        await send({"id":None,"method":"mining.set_difficulty","params":[diff]})

                elif m.get('method') in ('mining.subscribe','mining.authorize','mining.extranonce.subscribe'):
                    await send({"id":m.get('id'),"result":True,"error":None})
                else:
                    await send({"id":m.get('id'),"result":None,"error":None})

        except Exception:
            try: writer.close(); await writer.wait_closed()
            except: pass

    async def _stats_task(self):
        while True:
            try:
                st = self.engine.get_stats()
                import json
                self.q("INSERT OR REPLACE INTO engine_stats (id, template_prevhash, template_height, started_ts, pool_size_current, generated_since_template, top_score, top_hash_norm, top_entropy, w_hash, w_ent, last_update, top_list) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (st['template_prevhash'], st['template_height'], st['started_ts'], st['pool_size_current'], st['generated_since_template'], st['top_score'], st['top_hash_norm'], st['top_entropy'], st['w_hash'], st['w_ent'], st['last_update'], json.dumps(st.get('top_list') or [])))
                # append to series every 5 seconds
                if st['last_update'] % 5 == 0:
                    self.q("INSERT INTO engine_stats_series (ts, generated_since_template) VALUES (?, ?)", (st['last_update'], st['generated_since_template']))
            except Exception:
                pass
            await asyncio.sleep(1.0)
