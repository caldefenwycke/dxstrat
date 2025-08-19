DarwinX Stratum (MVP)

A V1 Stratum BTC mining pool with Darwin “A/B/C/X” header lane generation and matured-round payouts:

Miner login: wallet.worker (e.g., bc1q...yourwallet.worker1)

Stratum V1 (subscribe / authorize / set_difficulty / notify / submit)

Engine polls getblocktemplate and issues jobs (A/B/C/X lanes for header coverage)

Only pays when we find a block and it matures; splits that block’s subsidy among miners who submitted valid shares in that round, minus 2% pool fee

API: simple pool stats (/api/stats)

Systemd service files for VM deployment

Current MVP builds empty blocks (coinbase-only) for reliability. Once live, we can enable full templates (with tx fees + segwit commitment).
