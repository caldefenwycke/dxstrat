# Minimal Bech32 / Segwit parser (BIP-0173/350) for bc1 addresses
# Supports mainnet bc1q... (P2WPKH) and bc1p... (P2TR disabled here).

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def bech32_polymod(values):
    GEN = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        b = (chk >> 25) & 0xff
        chk = ((chk & 0x1ffffff) << 5) ^ v
        for i in range(5):
            chk ^= GEN[i] if ((b >> i) & 1) else 0
    return chk

def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def bech32_verify_checksum(hrp, data):
    return bech32_polymod(bech32_hrp_expand(hrp) + data) == 1

def bech32_decode(addr):
    addr = addr.strip()
    if (any(ord(x) < 33 or ord(x) > 126 for x in addr)): return (None, None)
    if (addr.lower() != addr and addr.upper() != addr): return (None, None)
    addr = addr.lower()
    pos = addr.rfind('1')
    if pos < 1 or pos + 7 > len(addr): return (None, None)
    hrp = addr[:pos]
    data = [CHARSET.find(c) for c in addr[pos+1:]]
    if any(x == -1 for x in data): return (None, None)
    if not bech32_verify_checksum(hrp, data): return (None, None)
    return (hrp, data[:-6])

def convert_bits(data, from_bits, to_bits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << to_bits) - 1
    for value in data:
        if value < 0 or (value >> from_bits):
            return None
        acc = (acc << from_bits) | value
        bits += from_bits
        while bits >= to_bits:
            bits -= to_bits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (to_bits - bits)) & maxv)
    elif bits >= from_bits or ((acc << (to_bits - bits)) & maxv):
        return None
    return ret

def decode_segwit_address(addr):
    hrp, data = bech32_decode(addr)
    if hrp != "bc":  # mainnet only
        return None
    if not data: return None
    ver = data[0]
    prog = bytes(convert_bits(data[1:], 5, 8, False) or [])
    if ver == 0 and len(prog) in (20, 32):
        return (ver, prog)
    # Limit scope to v0 P2WPKH/P2WSH for pool fee
    return None

def scriptpubkey_from_bech32(addr):
    seg = decode_segwit_address(addr)
    if not seg: 
        raise ValueError("Unsupported or invalid bech32 address")
    ver, prog = seg
    if ver == 0 and len(prog) == 20:  # P2WPKH
        return bytes([0x00, 0x14]) + prog  # OP_0 PUSH(20) <hash160>
    if ver == 0 and len(prog) == 32:  # P2WSH
        return bytes([0x00, 0x20]) + prog  # OP_0 PUSH(32) <sha256(script)>
    raise ValueError("Unsupported witness version/program for pool fee output")
