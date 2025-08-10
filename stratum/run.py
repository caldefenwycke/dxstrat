import asyncio, json
from pathlib import Path
from stratum.stratum_server import StratumServer, CONFIG_PATH

def load_cfg():
    p = Path("/opt/darwinx") / CONFIG_PATH
    with open(p, "r") as f:
        return json.load(f)

def main():
    cfg = load_cfg()
    srv = StratumServer(cfg)
    asyncio.run(srv.start())

if __name__ == "__main__":
    main()
