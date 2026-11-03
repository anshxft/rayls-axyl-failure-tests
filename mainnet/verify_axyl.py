"""How fast, and how final, is the Rayls Public Chain really? Measure Axyl consensus from the public RPC.

1. Every epoch record since launch (rayls_epochRecord): committee, blocks per epoch, certificate signers.
2. A live sampling window: does eth 'finalized' ever lag 'latest'? How often does a new commit land?
3. A recent block sample, decoded per the Axyl header encoding: who authored each block, how many are empty.
Usage: python verify_axyl.py [sample_seconds]
"""
import json, struct, sys, time, urllib.request
from collections import Counter
from datetime import datetime, timezone

RPC = "https://mainnet-rpc.rayls.com"
EXPLORER_RPC = "https://explorer.rayls.com/api/eth-rpc"   # independent index, used to cross-check block hashes
SAMPLE_S = int(sys.argv[1]) if len(sys.argv) > 1 else 60
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def post(url, body, tries=6):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "verify-axyl/1"})
    for i in range(tries):  # public endpoints flake; back off and retry
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as e:
            err = e
            time.sleep(2 ** i)
    raise RuntimeError(err)


rpc = lambda m, *p, url=RPC: post(url, {"jsonrpc": "2.0", "id": 1, "method": m, "params": list(p)})["result"]
batch = lambda calls: [r["result"] for r in sorted(post(RPC, [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]), key=lambda r: r["id"])]


def signers(b58):
    """signed_authorities is a base58 roaring bitmap (no-run format): return the set validator indices."""
    n = 0
    for c in b58:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    cookie, size = struct.unpack("<II", raw[:8])
    assert cookie == 12346, "unexpected bitmap format"
    heads = [struct.unpack("<HH", raw[8 + 4 * i: 12 + 4 * i]) for i in range(size)]
    pos, out = 8 + 8 * size, set()  # skip key/cardinality headers and the offset table
    for key, card in heads:
        vals = struct.unpack(f"<{card + 1}H", raw[pos: pos + 2 * (card + 1)])
        out |= {(key << 16) | v for v in vals}
        pos += 2 * (card + 1)
    return out


day = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
head = rpc("eth_getBlockByNumber", "latest", False)
cur_epoch = int(head["nonce"], 16) >> 32
print(f"Rayls chain {int(rpc('eth_chainId'), 16)}  head block {int(head['number'], 16):,}  epoch {cur_epoch}  ({day(int(head['timestamp'], 16))} UTC)\n")

# --- 1. epoch history ----------------------------------------------------------------------
recs = []
for e in range(cur_epoch):
    rec, cert = rpc("rayls_epochRecord", e)
    recs.append((e, rec["committee"], rec["next_committee"], rec["parent_state"]["number"], signers(cert["signed_authorities"])))
keysets = Counter(tuple(sorted(c)) for _, c, *_ in recs)
print("=== 1. Epoch records since launch ===")
print(f"epochs: {len(recs)}  distinct committees: {len(keysets)}  committee sizes: {sorted({len(c) for _, c, *_ in recs})}")
miss = Counter()
low = []
for e, c, _, last, s in recs:
    for i in set(range(len(c))) - s:
        miss[i] += 1
    if len(s) < len(c):
        low.append((e, len(s)))
quorum = lambda n: 2 * n // 3 + 1  # floor(2n/3) + 1, per the Axyl docs
changes = [e for (e, c, *_), (_, p, *_) in zip(recs[1:], recs) if len(c) != len(p)]
print(f"committee size changed at epoch(s): {changes}  ({len(recs[0][1])} -> {len(recs[-1][1])} validators)")
print(f"certificates signed by the whole committee: {len(recs) - len(low)} of {len(recs)}")
print(f"certificates with exactly the quorum (floor(2n/3)+1): {sum(1 for *_, c, _, _, s in recs if len(s) == quorum(len(c)))}"
      f"  below quorum: {sum(1 for *_, c, _, _, s in recs if len(s) < quorum(len(c)))}")
print("missed signatures by committee index:", dict(sorted(miss.items())) or "none")
lasts = [last for *_, last, _ in recs]
per_epoch = [b - a for a, b in zip([0] + lasts, lasts)]
full = per_epoch[1:]  # epoch 0 starts at genesis, keep only complete epochs after it
avg_bt = sum(86400 / x for x in full) / len(full)
print(f"blocks per epoch (24 h): min {min(full):,}  median {sorted(full)[len(full) // 2]:,}  max {max(full):,}")
print(f"=> average block time {avg_bt:.3f} s  (min {86400 / max(full):.3f} s, max {86400 / min(full):.3f} s)")
print(f"last 5 epochs blocks: {per_epoch[-5:]}")
json.dump([{"epoch": e, "blocks": b, "signers": len(s), "committee": len(c)} for (e, c, _, _, s), b in zip(recs, per_epoch)], open("epochs.json", "w"))

# --- 2. live finality and commit cadence -----------------------------------------------------
print(f"\n=== 2. Live window: {SAMPLE_S} s, polling latest/safe/finalized every ~250 ms ===")
lags, arrivals, seen, t_end = [], [], None, time.time() + SAMPLE_S
while time.time() < t_end:
    t = time.time()
    lat, safe, fin = batch([("eth_blockNumber", []), ("eth_getBlockByNumber", ["safe", False]), ("eth_getBlockByNumber", ["finalized", False])])
    lat = int(lat, 16)
    lags.append((lat - int(safe["number"], 16), lat - int(fin["number"], 16)))
    if lat != seen:
        arrivals.append((t, lat))
        seen = lat
    time.sleep(max(0, 0.25 - (time.time() - t)))
print(f"samples: {len(lags)}  max (latest - safe): {max(a for a, _ in lags)}  max (latest - finalized): {max(b for _, b in lags)}")
gaps = [b[0] - a[0] for a, b in zip(arrivals, arrivals[1:])]
jumps = [b[1] - a[1] for a, b in zip(arrivals, arrivals[1:])]
print(f"new head observed {len(arrivals)} times; median gap {sorted(gaps)[len(gaps) // 2]:.2f} s; mean gap {sum(gaps) / len(gaps):.2f} s; blocks per update {Counter(jumps).most_common(3)}")

# --- 3. recent block sample ------------------------------------------------------------------
N = 3000
top = int(rpc("eth_blockNumber"), 16)
blocks = []
for lo in range(top - N + 1, top + 1, 100):
    blocks += batch([("eth_getBlockByNumber", [hex(n), False]) for n in range(lo, min(lo + 100, top + 1))])
auth = Counter(b["miner"] for b in blocks)
empty = sum(1 for b in blocks if not b["transactions"])
rounds = [int(b["nonce"], 16) & 0xFFFFFFFF for b in blocks]
span = int(blocks[-1]["timestamp"], 16) - int(blocks[0]["timestamp"], 16)
print(f"\n=== 3. Last {N:,} blocks ({day(int(blocks[0]['timestamp'], 16))} to {day(int(blocks[-1]['timestamp'], 16))}) ===")
print(f"distinct block authors (coinbase): {len(auth)}")
for a, k in auth.most_common():
    print(f"  {a}  {k:>5} blocks  {k / N:.1%}")
print(f"empty blocks: {empty:,} of {N:,} ({empty / N:.1%})")
print(f"consensus rounds advanced: {rounds[-1] - rounds[0]:,} in {span} s -> {(rounds[-1] - rounds[0]) / span:.2f} rounds/s; blocks/s {N / span:.2f}")

# cross-check 20 block hashes against the explorer's own index
picks = [blocks[i] for i in range(0, N, N // 20)]
same = sum(1 for b in picks if rpc("eth_getBlockByNumber", b["number"], False, url=EXPLORER_RPC)["hash"] == b["hash"])
print(f"block hashes matching the explorer index: {same}/{len(picks)}")
stats = json.load(urllib.request.urlopen(urllib.request.Request("https://explorer.rayls.com/api/v2/stats", headers={"User-Agent": "verify-axyl/1"}), timeout=60))
print(f"explorer totals: {int(stats['total_blocks']):,} blocks, {int(stats['total_transactions']):,} txs -> {int(stats['total_transactions']) / int(stats['total_blocks']):.3f} tx per block")
