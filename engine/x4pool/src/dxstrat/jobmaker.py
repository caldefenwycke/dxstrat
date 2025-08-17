import os, time
from typing import Dict, Any
from .rpc import getblocktemplate, getaddressinfo
from .utils import build_coinbase_split, merkle_branch

GBT_INTERVAL = int(os.getenv("GBT_INTERVAL","8"))
EX1_SIZE = int(os.getenv("EXTRANONCE1_SIZE","4"))
EX2_SIZE = int(os.getenv("EXTRANONCE2_SIZE","4"))
PAYOUT_ADDRESS = os.getenv("PAYOUT_ADDRESS","")

LANE_BYTES = {
    "A": b"DXA1",
    "B": b"DXB1",
    "C": b"DXC1",
    "D": b"DXD1",
}

class TemplateState:
    def __init__(self):
        self.last_tmpl = None
        self.last_ts   = 0
        self.job_seq   = 0
        self.payout_spk = None

    def refresh(self):
        now = time.time()
        if (self.last_tmpl is None) or (now - self.last_ts >= GBT_INTERVAL):
            tmpl = getblocktemplate()
            self.last_tmpl = tmpl
            self.last_ts = now
            self.job_seq += 1
        return self.last_tmpl, self.job_seq

    def payout_script(self) -> str:
        if self.payout_spk: return self.payout_spk
        if not PAYOUT_ADDRESS:
            raise RuntimeError("PAYOUT_ADDRESS not set in .env")
        info = getaddressinfo(PAYOUT_ADDRESS)
        spk = info.get("scriptPubKey")
        if not spk:
            raise RuntimeError(f"Could not resolve scriptPubKey for {PAYOUT_ADDRESS}")
        self.payout_spk = spk
        return spk

class X4JobMaker:
    def __init__(self):
        self.tpl = TemplateState()
        self.rr = 0

    def next_lane(self) -> str:
        lane = ["A","B","C","D"][self.rr % 4]
        self.rr += 1
        return lane

    def make_job(self, forced_lane: str = None) -> Dict[str, Any]:
        tmpl, job_seq = self.tpl.refresh()
        lane = forced_lane or self.next_lane()
        payout_spk = self.tpl.payout_script()
        commit_spk = tmpl.get("default_witness_commitment")
        if not commit_spk:
            raise RuntimeError("Template missing default_witness_commitment")

        height = tmpl["height"]
        coinbase_value = int(tmpl["coinbasevalue"])

        lane_flags = LANE_BYTES[lane] + job_seq.to_bytes(4, "little")

        coinb1, coinb2 = build_coinbase_split(
            height=height,
            lane_flags=lane_flags,
            en1_size=EX1_SIZE,
            en2_size=EX2_SIZE,
            payout_spk_hex=payout_spk,
            witness_commitment_spk_hex=commit_spk,
            coinbase_value_sats=coinbase_value
        )

        # Merkle branch with cb path (we’ll recompute txid after miner inserts extranonces)
        txids_be = ["00"*32] + [tx["txid"] for tx in tmpl.get("transactions", [])]
        branch, merkle_root_be = merkle_branch(txids_be)

        job_id = f"{job_seq}-{lane}"
        return {
            "job_id": job_id,
            "lane": lane,
            "height": height,
            "version": tmpl["version"],
            "prevhash_be": tmpl["previousblockhash"],
            "nbits": tmpl["bits"],
            "ntime": int(time.time()),
            "coinb1": coinb1,
            "coinb2": coinb2,
            "merkle_branch": branch,
            "tmpl": tmpl,
            "extranonce2_size": EX2_SIZE,
        }
