import hashlib

def dsha256(b: bytes)->bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()

def merkle_root(tx_hashes_le):
    if not tx_hashes_le: return b'\x00'*32
    layer=tx_hashes_le[:]
    while len(layer)>1:
        if len(layer)%2==1: layer.append(layer[-1])
        layer=[dsha256(layer[i]+layer[i+1]) for i in range(0,len(layer),2)]
    return layer[0]

def varint(n:int)->bytes:
    if n<0xfd: return n.to_bytes(1,'little')
    if n<=0xffff: return b'\xfd'+n.to_bytes(2,'little')
    if n<=0xffffffff: return b'\xfe'+n.to_bytes(4,'little')
    return b'\xff'+n.to_bytes(8,'little')

def serialize_tx(outputs, coinbase_script: bytes, locktime: int = 0) -> bytes:
    # Minimal non-segwit coinbase (marker/flag omitted; witness commitment is an OP_RETURN output)
    version = (2).to_bytes(4,'little')
    tx_in_count = varint(1)
    prevout = b'\x00'*32 + (0xffffffff).to_bytes(4,'little')
    script_len = varint(len(coinbase_script))
    sequence = (0xffffffff).to_bytes(4,'little')
    out_count = varint(len(outputs))
    outs = b''.join([
        o['value'].to_bytes(8,'little', signed=False) + varint(len(o['spk'])) + o['spk']
        for o in outputs
    ])
    lock = locktime.to_bytes(4,'little')
    return b''.join([version, tx_in_count, prevout, script_len, coinbase_script, sequence, out_count, outs, lock])

def build_coinbase_tx(coinbase_script: bytes, reward_sats: int, payout_spk: bytes, witness_commitment_spk: bytes | None) -> bytes:
    outs = []
    # Coinbase pays full reward to pool address; witness commitment is zero-value OP_RETURN
    outs.append({"value": reward_sats, "spk": payout_spk})
    if witness_commitment_spk is not None:
        outs.append({"value": 0, "spk": witness_commitment_spk})
    return serialize_tx(outs, coinbase_script, 0)
