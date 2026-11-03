"""Test F: same sender, same nonce, two different payments, sent at once to two different validators.

A double spend would show as both settling. For each trial we record which payment won, whether the loser ever
gets a receipt on any node, whether every node agrees, and whether the balance moved by exactly one payment + fee.
Usage: python conflict.py [trials]
"""
import json, os, subprocess, sys, threading, time
import faults as F
import harness as H

ADDR = H.KEY["address"]
TO_A, TO_B = "0x000000000000000000000000000000000000A001", "0x000000000000000000000000000000000000B002"
WAIT = 20


def sign(url, to, value, nonce, base):
    raw = subprocess.check_output(["cast", "mktx", to, "--value", str(value), "--nonce", str(nonce), "--gas-limit", "21000", "--gas-price", str(base * 4),
                                   "--priority-gas-price", "0", "--chain", str(int(H.rpc(url, "eth_chainId"), 16)), "--private-key", H.KEY["private_key"], "--rpc-url", url], text=True).strip()
    return raw, subprocess.check_output(["cast", "keccak", raw], text=True).strip()


def send(url, raw, out, key):
    try:
        out[key] = {"ack": H.rpc(url, "eth_sendRawTransaction", raw), "t": time.time()}
    except Exception as e:
        out[key] = {"error": str(e)[:160], "t": time.time()}


def receipts(h):
    res = {}
    for u in H.NODES:
        r = H.rpc(u, "eth_getTransactionReceipt", h)
        res[u[-4:]] = {"block": int(r["blockNumber"], 16), "hash": r["blockHash"], "status": int(r["status"], 16), "gas": int(r["gasUsed"], 16), "price": int(r["effectiveGasPrice"], 16)} if r else None
    return res


def trial(i):
    a, b = i % 4, (i + 1 + i // 4) % 4
    if a == b:
        b = (b + 1) % 4
    ua, ub = H.NODES[a], H.NODES[b]
    nonce = int(H.rpc(ua, "eth_getTransactionCount", ADDR, "latest"), 16)
    base = int(H.rpc(ua, "eth_getBlockByNumber", "latest", False)["baseFeePerGas"], 16)
    ra, ha = sign(ua, TO_A, 1000 + i, nonce, base)
    rb, hb = sign(ub, TO_B, 2000 + i, nonce, base)
    bal0 = int(H.rpc(ua, "eth_getBalance", ADDR, "latest"), 16)
    acks = {}
    ts = [threading.Thread(target=send, args=(ua, ra, acks, "A")), threading.Thread(target=send, args=(ub, rb, acks, "B"))]
    [t.start() for t in ts]; [t.join() for t in ts]
    time.sleep(WAIT)
    ga, gb = receipts(ha), receipts(hb)
    wa, wb = [v for v in ga.values() if v], [v for v in gb.values() if v]
    winner = "both" if wa and wb else "A" if wa else "B" if wb else "none"
    w = (wa or wb or [None])[0]
    bal1 = {u[-4:]: int(H.rpc(u, "eth_getBalance", ADDR, "latest"), 16) for u in H.NODES}
    fee = w["gas"] * w["price"] if w else 0
    value = (1000 + i) if winner == "A" else (2000 + i) if winner == "B" else 0
    rec = {"trial": i, "sent_to": [a, b], "nonce": nonce, "acks": acks, "winner": winner, "receipts_A": ga, "receipts_B": gb,
           "nodes_with_winner_receipt": len(wa or wb), "same_block_hash": len({v["hash"] for v in (wa or wb)}) <= 1,
           "balance_delta_ok": {k: bal0 - v == fee + value for k, v in bal1.items()}, "nonce_after": {u[-4:]: int(H.rpc(u, "eth_getTransactionCount", ADDR, "latest"), 16) for u in H.NODES}}
    print(json.dumps({k: rec[k] for k in ("trial", "sent_to", "winner", "nodes_with_winner_receipt", "same_block_hash", "nonce_after")}), {k: ("ok" if "ack" in v else v["error"][:70]) for k, v in acks.items()}, "balance_ok", all(rec["balance_delta_ok"].values()), flush=True)
    return rec


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    print(F.ctl("reset", ADDR)); time.sleep(60); F.wait_all_up()
    rows = [trial(i) for i in range(n)]
    json.dump(rows, open("results/F_conflict.json", "w"), indent=1)
    c = {w: sum(1 for r in rows if r["winner"] == w) for w in ("A", "B", "both", "none")}
    print("winners", c, "| all nodes agree:", sum(r["nodes_with_winner_receipt"] == 4 and r["same_block_hash"] for r in rows), "/", n,
          "| balance exact on every node:", sum(all(r["balance_delta_ok"].values()) for r in rows), "/", n,
          "| both acked at submit:", sum(all("ack" in v for v in r["acks"].values()) for r in rows), "/", n)
