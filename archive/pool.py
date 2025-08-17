import os, time, threading, random, json
from .rpc import Rpc
from .entropy import byte_entropy_score
from .coinbase import dsha256, merkle_root, build_coinbase_tx
from .bech32 import scriptpubkey_from_bech32

class DarwinXEngine:
    def __init__(self,cfg):
        self.cfg=cfg
        r=cfg['rpc']
        self.rpc=Rpc(r['host'],r['port'],r['user'],r['password'])
        e=cfg['engine']
        self.pool_size=e['rolling_pool_size']
        self.w_hash=e['score_weight_hash']
        self.w_ent=e['score_weight_entropy']
        self.ntime_drift=e['ntime_drift_seconds']
        self.pool=[]
        self.lock=threading.Lock()
        self.template=None
        self.template_ts=0
        self.counter=0

    def refresh_template(self):
        self.template=self.rpc.getblocktemplate()
        self.template_ts=int(time.time())
        with self.lock:
            self.pool.clear()

    def reward_sats(self): 
        return int(self.template['coinbasevalue'])

    def build_job(self):
        t=self.template
        tag=self.cfg['pool']['coinbase_tag'].encode()
        extranonce=os.urandom(8)
        coinbase_script = tag + b'/' + extranonce

        # payout script from bech32
        payout_spk = scriptpubkey_from_bech32(self.cfg['pool']['pool_fee_address'])

        # witness commitment spk from template (if present)
        wcommit = t.get('default_witness_commitment')
        wcommit_spk = bytes.fromhex(wcommit) if wcommit else None

        coinbase_tx = build_coinbase_tx(coinbase_script, self.reward_sats(), payout_spk, wcommit_spk)
        coinbase_txid_le = dsha256(coinbase_tx)[::-1]

        # Use full transactions hex ("data") for block assembly, and txids for merkle calc
        tx_datas = [tx['data'] for tx in t.get('transactions',[])]
        txids_le = [bytes.fromhex(tx['txid'])[::-1] for tx in t.get('transactions',[])]
        root = merkle_root([coinbase_txid_le] + txids_le)

        version = int(t['version']).to_bytes(4,'little')
        prev = bytes.fromhex(t['previousblockhash'])[::-1]
        cur=max(int(time.time()), int(t['curtime']))
        ntime = cur + random.randint(-self.ntime_drift, self.ntime_drift)
        if ntime < int(t['curtime']): ntime = int(t['curtime'])
        nbits = bytes.fromhex(t['bits'])[::-1]
        nonce = (0).to_bytes(4,'little')

        header = b''.join([version, prev, root[::-1], ntime.to_bytes(4,'little'), nbits, nonce])
        hv = dsha256(header)
        hash_norm = int.from_bytes(hv,'big')/(2**256-1)
        ent = byte_entropy_score(root)
        score = self.w_hash*(1.0-hash_norm) + self.w_ent*(1.0-ent)

        self.counter+=1
        jid=f"{int(time.time())}-{self.counter:08d}"

        return {
            'job_id': jid,
            'version': version.hex(),
            'prevhash': prev[::-1].hex(),
            'merkle_root': root[::-1].hex(),
            'ntime': f"{ntime:08x}",
            'nbits': t['bits'],
            'clean_jobs': True,
            'exclusive': True,
            'score': score,
            'reward_sats': self.reward_sats(),
            'height': t.get('height'),
            # Assembly payloads:
            'coinbase_tx': coinbase_tx.hex(),
            'txs': tx_datas,  # list of hex strings
            'witness_commitment': wcommit if wcommit else None
        }

    def loop(self):
        while True:
            now=int(time.time())
            if not self.template or now-self.template_ts>15:
                self.refresh_template()
            need=max(0, self.pool_size - len(self.pool))
            batch=min(512, need)
            if batch>0:
                created=[self.build_job() for _ in range(batch)]
                with self.lock:
                    self.pool.extend(created)
                    self.pool.sort(key=lambda j:j['score'], reverse=True)
                    self.pool=self.pool[:self.pool_size]
            time.sleep(0.2)

    def lease_best_job(self):
        with self.lock:
            if not self.pool: return None
            return self.pool.pop(0)

    def get_stats(self):
        with self.lock:
            top_list = []
            for j in (self.pool[:20] if self.pool else []):
                top_list.append({
                    'job_id': j.get('job_id'),
                    'score': j.get('score'),
                    'hash_norm': j.get('hash_norm'),
                    'entropy': j.get('entropy')
                })
            return {
                'template_prevhash': (self.template['previousblockhash'] if self.template else None),
                'template_height': (self.template.get('height') if self.template else None),
                'started_ts': self.template_ts,
                'pool_size_current': self.last_pool_len,
                'generated_since_template': int(self.generated_since_template),
                'top_score': (self.last_top.get('score') if self.last_top else None),
                'top_hash_norm': (self.last_top.get('hash_norm') if self.last_top and 'hash_norm' in self.last_top else None),
                'top_entropy': (self.last_top.get('entropy') if self.last_top and 'entropy' in self.last_top else None),
                'w_hash': self.cfg['engine']['score_weight_hash'],
                'w_ent': self.cfg['engine']['score_weight_entropy'],
                'last_update': int(time.time()), 'top_list': top_list
            }
