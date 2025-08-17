import struct, hashlib
from typing import List, Tuple

# === Hash helpers ===
def sha256(b: bytes) -> bytes: return hashlib.sha256(b).digest()
def dblsha(b: bytes) -> bytes: return sha256(sha256(b))
def u32le(n: int) -> bytes:    return struct.pack("<L", n & 0xffffffff)
def u64le(n: int) -> bytes:    return struct.pack("<Q", n & 0xffffffffffffffff)

def varint(n: int) -> bytes:
    if n < 0xfd: return bytes([n])
    if n <= 0xffff: return b"\xfd" + struct.pack("<H", n)
    if n <= 0xffffffff: return b"\xfe" + struct.pack("<L", n)
    return b"\xff" + struct.pack("<Q", n)

def pushdata(b: bytes) -> bytes:
    l = len(b)
    if l < 0x4c:   return bytes([l]) + b
    if l <= 0xff:  return b"\x4c" + bytes([l]) + b
    if l <= 0xffff:return b"\x4d" + struct.pack("<H", l) + b
    return b"\x4e" + struct.pack("<L", l) + b

# === Difficulty / target ===
DIFF1_BITS = 0x1d00ffff
def target_from_nbits(nbits_hex: str) -> int:
    n = int(nbits_hex, 16); exp = n >> 24; mant = n & 0xffffff
    return mant << (8*(exp-3))
DIFF1_TARGET = target_from_nbits(f"{DIFF1_BITS:08x}")

def target_from_difficulty(diff: float) -> int:
    if diff <= 0: diff = 1.0
    return int(DIFF1_TARGET / diff)

def hash_to_int(h32: bytes) -> int:
    return int.from_bytes(h32[::-1], "big")

# === Merkle helpers ===
def merkle_branch(txids_be: List[str]) -> Tuple[List[str], str]:
    """
    Returns (branch list BE hex, merkle_root BE hex) for a list with coinbase txid first.
    Branch contains siblings (BE hex) along coinbase path.
    """
    layer = [bytes.fromhex(x)[::-1] for x in txids_be]  # to LE
    if not layer: raise ValueError("Empty txid list")

    branch = []; idx = 0; cur = layer[:]
    while len(cur) > 1:
        if len(cur) & 1: cur.append(cur[-1])
        pair = []
        for i in range(0, len(cur), 2):
            pair.append(dblsha(cur[i] + cur[i+1]))
        sib = cur[idx ^ 1]
        branch.append(sib[::-1].hex())  # BE
        idx //= 2
        cur = pair
    merkle_root_be = cur[0][::-1].hex()
    return branch, merkle_root_be

# === Coinbase split (segwit) ===
def build_coinbase_split(height: int,
                         lane_flags: bytes,
                         en1_size: int,
                         en2_size: int,
                         payout_spk_hex: str,
                         witness_commitment_spk_hex: str,
                         coinbase_value_sats: int):
    """
    SegWit coinbase with scriptSig = [height] [lane_flags] [en1] [en2].
    We return (coinb1, coinb2) so miner builds coinbase = coinb1 + extranonce1 + extranonce2 + coinb2
    """
    # BIP34 height minimal encoding
    h = height; enc = bytearray()
    while True:
        enc.append(h & 0xff); h >>= 8
        if h == 0: break
    bip34 = bytes(enc)

    en1_placeholder = b"\x00" * en1_size
    en2_placeholder = b"\x00" * en2_size

    ss  = pushdata(bip34)
    ss += pushdata(lane_flags)
    ss += bytes([en1_size]) + en1_placeholder
    ss += bytes([en2_size]) + en2_placeholder

    version = b"\x02\x00\x00\x00"
    marker_flag = b"\x00\x01"
    vin_cnt = varint(1)
    prevout = (b"\x00"*32) + b"\xff\xff\xff\xff"
    seq = b"\xff\xff\xff\xff"
    txin = prevout + varint(len(ss)) + ss + seq

    payout_spk = bytes.fromhex(payout_spk_hex)
    wit_spk = bytes.fromhex(witness_commitment_spk_hex)
    vout_cnt = varint(2)
    vout0 = u64le(coinbase_value_sats) + varint(len(payout_spk)) + payout_spk
    vout1 = u64le(0) + varint(len(wit_spk)) + wit_spk

    witness = varint(1) + varint(32) + (b"\x00" * 32)
    locktime = b"\x00\x00\x00\x00"

    full = version + marker_flag + vin_cnt + txin + vout_cnt + vout0 + vout1 + witness + locktime

    # find en1/en2 placeholders to split at exact boundaries
    en1_seq = bytes([en1_size]) + en1_placeholder
    en2_seq = bytes([en2_size]) + en2_placeholder
    off_en1 = full.find(en1_seq)
    if off_en1 < 0: raise RuntimeError("Could not locate extranonce1 placeholder")
    off_en2 = full.find(en2_seq, off_en1 + len(en1_seq))
    if off_en2 < 0: raise RuntimeError("Could not locate extranonce2 placeholder")

    coinb1 = full[:off_en1+1]                   # include PUSHDATA opcode for en1
    coinb2 = full[off_en2+1+en2_size:]          # after en2 data

    return coinb1.hex(), coinb2.hex()

def txid_from_tx_hex(segwit_tx_hex: str) -> str:
    """
    Legacy TXID (no-witness hash) BE hex for segwit tx hex.
    """
    tx = bytes.fromhex(segwit_tx_hex)

    def read_varint(b, i):
        fb = b[i]
        if fb < 0xfd: return fb, i+1
        if fb == 0xfd: return int.from_bytes(b[i+1:i+3], "little"), i+3
        if fb == 0xfe: return int.from_bytes(b[i+1:i+5], "little"), i+5
        return int.from_bytes(b[i+1:i+9], "little"), i+9

    i = 4; segwit = False
    if tx[i] == 0 and tx[i+1] == 1:
        segwit = True; i += 2
    vin_cnt, i = read_varint(tx, i)
    vins = []
    for _ in range(vin_cnt):
        prev = tx[i:i+36]; i += 36
        slen, i = read_varint(tx, i)
        ss = tx[i:i+slen]; i += slen
        seq = tx[i:i+4]; i += 4
        vins.append((prev, ss, seq))
    vout_cnt, i = read_varint(tx, i)
    vouts = []
    for _ in range(vout_cnt):
        val = tx[i:i+8]; i += 8
        slen, i = read_varint(tx, i)
        spk = tx[i:i+slen]; i += slen
        vouts.append((val, spk))
    if segwit:
        for _ in range(vin_cnt):
            wcnt, i = read_varint(tx, i)
            for __ in range(wcnt):
                wlen, i = read_varint(tx, i)
                i += wlen
    lock = tx[i:i+4]

    # rebuild no-witness serialization
    out = tx[:4] + varint(vin_cnt)
    i = 4
    if segwit: i = 6
    vin_cnt2, i = read_varint(tx, i)
    out = tx[:4] + varint(vin_cnt2)
    for _ in range(vin_cnt2):
        prev = tx[i:i+36]; i += 36
        slen, i = read_varint(tx, i)
        ss = tx[i:i+slen]; i += slen
        seq = tx[i:i+4]; i += 4
        out += prev + varint(len(ss)) + ss + seq
    vout_cnt2, i = read_varint(tx, i)
    out += varint(vout_cnt2)
    for _ in range(vout_cnt2):
        val = tx[i:i+8]; i += 8
        slen, i = read_varint(tx, i)
        spk = tx[i:i+slen]; i += slen
        out += val + varint(len(spk)) + spk
    out += tx[i:i+4]  # locktime
    return dblsha(out)[::-1].hex()
