import json, asyncio
from stratum_server import StratumServer

def load_cfg():
    with open('config/config.json','r',encoding='utf-8') as f:
        return json.load(f)

async def main():
    server = StratumServer(load_cfg())
    await server.start()

if __name__ == '__main__':
    asyncio.run(main())
