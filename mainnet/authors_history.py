"""Block authorship across the whole chain: sample every STEP-th block, bucket by epoch (decoded from the header nonce).
Writes authors_by_epoch.json for the chart and prints when each validator was last seen authoring.
Usage: python authors_history.py [step]
"""
import json, sys, time, urllib.request
from collections import Counter, defaultdict

RPC = "https://mainnet-rpc.rayls.com"
STEP = int(sys.argv[1]) if len(sys.argv) > 1 else 2000


def post(body, tries=6):
    req = urllib.request.Request(RPC, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "verify-axyl/1"})
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            err = e
            time.sleep(2 ** i)
    raise RuntimeError(err)


top = int(post({"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})["result"], 16)
heights = list(range(1, top + 1, STEP))
by_epoch, last_seen = defaultdict(Counter), {}
for i in range(0, len(heights), 100):
    res = post([{"jsonrpc": "2.0", "id": n, "method": "eth_getBlockByNumber", "params": [hex(n), False]} for n in heights[i:i + 100]])
    for r in res:
        b = r["result"]
        ep, who, n = int(b["nonce"], 16) >> 32, b["miner"].lower(), int(b["number"], 16)
        by_epoch[ep][who] += 1
        last_seen[who] = max(last_seen.get(who, (0, 0)), (n, ep))
json.dump({str(e): dict(c) for e, c in sorted(by_epoch.items())}, open("authors_by_epoch.json", "w"))
print(f"sampled {len(heights):,} blocks (every {STEP:,}th) up to {top:,}")
for who, (n, ep) in sorted(last_seen.items(), key=lambda x: x[1]):
    first = min(e for e, c in by_epoch.items() if who in c)
    print(f"{who}  first seen epoch {first:>3}  last seen block {n:>10,} (epoch {ep})  samples {sum(c[who] for c in by_epoch.values()):>5}")
