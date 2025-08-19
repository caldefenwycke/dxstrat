#!/usr/bin/env python3
import asyncio, json, os, hashlib, ipaddress

CKHOST = os.getenv("CKPOOL_BIND","127.0.0.1")
CKPORT = int(os.getenv("CKPOOL_PORT","3334"))
PUBHOST = os.getenv("STRATUM_PUBLIC_HOST","0.0.0.0")
PUBPORT = int(os.getenv("STRATUM_PUBLIC_PORT","3333"))

# Lanes: A,B,C,X masks
LANE_MASKS = (0x20000000, 0x30000000, 0xA0000000, 0xB0000000)

def lane_for_addr(peername):
    host,port = peername[0], peername[1]
    try:
        ip = ipaddress.ip_address(host)
        key = ip.packed + port.to_bytes(2,'big')
    except Exception:
        key = (host+str(port)).encode()
    h = hashlib.blake2s(key, digest_size=1).digest()[0] & 0x03
    return h  # 0..3

def patch_configure(obj):
    # obj: {"id":..,"method":"mining.configure","params":[features, options]}
    if not isinstance(obj.get("params"), list) or not obj["params"]:
        return obj
    feats = obj["params"][0]
    if isinstance(feats, list) and "version-rolling" in feats:
        feats = [f for f in feats if f != "version-rolling"]
        obj["params"][0] = feats
        if len(obj["params"]) > 1 and isinstance(obj["params"][1], dict):
            obj["params"][1].pop("version-rolling.mask", None)
    return obj

def patch_notify(obj, lane):
    # Stratum notify params: [job_id, prevhash, coinb1, coinb2, merkle_branch, version, nbits, ntime, clean]
    if obj.get("method") != "mining.notify": return obj
    ps = obj.get("params", [])
    if len(ps) < 9: return obj
    try:
        basever = int(ps[5], 16)
        ps[5] = f"{(basever | LANE_MASKS[lane]) & 0xffffffff:08x}"
    except Exception:
        pass
    return obj

async def pipe(reader, writer, transform=None):
    while True:
        line = await reader.readline()
        if not line: break
        try:
            obj = json.loads(line.decode().strip())
        except Exception:
            writer.write(line); await writer.drain(); continue
        if transform:
            obj = transform(obj)
            line = (json.dumps(obj) + "\n").encode()
        writer.write(line); await writer.drain()
    writer.close()
    try: await writer.wait_closed()
    except: pass

async def handle_client(miner_r, miner_w):
    peer = miner_w.get_extra_info('peername')
    lane = lane_for_addr(peer)

    # Upstream connection
    pool_r, pool_w = await asyncio.open_connection(CKHOST, CKPORT)

    # Miner -> Pool: strip version-rolling on configure
    async def m2p():
        async def tr(obj):
            if obj.get("method")=="mining.configure":
                obj = patch_configure(obj)
            return obj
        # small wrapper to call transform per line
        while True:
            line = await miner_r.readline()
            if not line: break
            try:
                obj = json.loads(line.decode().strip())
                obj = await tr(obj)
                line = (json.dumps(obj)+"\n").encode()
            except Exception:
                pass
            pool_w.write(line); await pool_w.drain()
        try: pool_w.close(); await pool_w.wait_closed()
        except: pass

    # Pool -> Miner: patch version in mining.notify
    async def p2m():
        while True:
            line = await pool_r.readline()
            if not line: break
            try:
                obj = json.loads(line.decode().strip())
                obj = patch_notify(obj, lane)
                line = (json.dumps(obj)+"\n").encode()
            except Exception:
                pass
            miner_w.write(line); await miner_w.drain()
        try: miner_w.close(); await miner_w.wait_closed()
        except: pass

    await asyncio.gather(m2p(), p2m())

async def main():
    server = await asyncio.start_server(handle_client, PUBHOST, PUBPORT)
    addr = ", ".join(str(s.getsockname()) for s in server.sockets)
    print(f"lanes-proxy listening on {addr} -> {CKHOST}:{CKPORT}", flush=True)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
