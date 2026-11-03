"""Send real signed payments to the local 4-validator Axyl network and time them on every node.

Usage: python harness.py <label> [payments] [gap_seconds] [submit_node_index]
Writes results/<label>.json. Every payment records submit time, per-node receipt time, block and hash.
"""
import json, os, statistics, subprocess, sys, threading, time, urllib.request

NODES = ["http://127.0.0.1:8545", "http://127.0.0.1:8544", "http://127.0.0.1:8543", "http://127.0.0.1:8542"]
TO = "0x000000000000000000000000000000000000dEaD"
KEY = json.load(open("lab/testkey.json"))["data"]
KEY = KEY[0] if isinstance(KEY, list) else KEY
KEY = KEY.get("accounts", [KEY])[0]


def rpc(url, method, *params, timeout=3):
    req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)}).encode(), {"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]


def alive(url):
    try:
        return int(rpc(url, "eth_blockNumber", timeout=1), 16)
    except Exception:
        return None


def presign(url, nonce_start, n, value=1):
    """Sign offline ahead of time so signing cost is not part of the measured latency."""
    chain = int(rpc(url, "eth_chainId"), 16)
    base = int(rpc(url, "eth_getBlockByNumber", "latest", False)["baseFeePerGas"], 16)
    out = []
    for i in range(n):
        raw = subprocess.check_output(["cast", "mktx", TO, "--value", str(value + i), "--nonce", str(nonce_start + i), "--gas-limit", "21000",
                                       "--gas-price", str(base * 4), "--priority-gas-price", "0", "--chain", str(chain),
                                       "--private-key", KEY["private_key"], "--rpc-url", url], text=True).strip()
        h = subprocess.check_output(["cast", "keccak", raw], text=True).strip()
        out.append((raw, h))
    return out


def watch(tx_hash, urls, result, deadline):
    """Poll one node until its receipt appears; record arrival time and what the node reports as final."""
    def one(url):
        while time.time() < deadline:
            try:
                r = rpc(url, "eth_getTransactionReceipt", tx_hash, timeout=2)
            except Exception:
                r = None
            if r:
                t = time.time()
                try:
                    fin = int(rpc(url, "eth_getBlockByNumber", "finalized", False, timeout=2)["number"], 16)
                except Exception:
                    fin = None
                result[url] = {"t": t, "block": int(r["blockNumber"], 16), "block_hash": r["blockHash"], "status": int(r["status"], 16),
                               "tx_index": int(r["transactionIndex"], 16), "finalized_at_receipt": fin}
                return
            time.sleep(0.025)
    ts = [threading.Thread(target=one, args=(u,), daemon=True) for u in urls]
    [t.start() for t in ts]
    return ts


def run(label, n=30, gap=2.0, submit=0, wait=30, hooks=None):
    """hooks maps payment index -> callable run just before that payment is submitted."""
    hooks = hooks or {}
    url = NODES[submit]
    nonce = int(rpc(url, "eth_getTransactionCount", KEY["address"], "pending"), 16)
    signed = presign(url, nonce, n)
    records, threads, events = [], [], []
    for i, (raw, h) in enumerate(signed):
        if i in hooks:
            events.append({"before_payment": i, "t": time.time(), "note": hooks[i]()})
        res = {}
        up = [alive(u) is not None for u in NODES]  # health check BEFORE the timer: it must not count as latency
        rec = {"i": i, "hash": h, "nonce": nonce + i, "per_node": res, "up_at_submit": up, "t_submit": time.time()}
        try:
            rec["ack"] = rpc(url, "eth_sendRawTransaction", raw)
        except Exception as e:
            rec["submit_error"] = str(e)[:200]
        rec["t_ack"] = time.time()
        threads += watch(h, NODES, res, rec["t_submit"] + wait)
        records.append(rec)
        time.sleep(gap)
    for t in threads:
        t.join()
    os.makedirs("results", exist_ok=True)
    out = {"label": label, "n": n, "gap_s": gap, "submit_node": url, "created": time.time(), "events": events, "records": records,
           "final_heights": [alive(u) for u in NODES], "commit": open("lab/commit.txt").read().strip() if os.path.exists("lab/commit.txt") else None}
    json.dump(out, open(f"results/{label}.json", "w"), indent=1)
    return out


def summarize(out):
    lat, spread, missing, mismatched, not_final = [], [], 0, 0, 0
    for r in out["records"]:
        got = r["per_node"]
        if not got:
            missing += 1
            continue
        ts = [v["t"] for v in got.values()]
        lat.append(min(ts) - r["t_submit"])
        spread.append(max(ts) - min(ts))
        if len({v["block_hash"] for v in got.values()}) > 1:
            mismatched += 1
        not_final += sum(1 for v in got.values() if v["finalized_at_receipt"] is not None and v["finalized_at_receipt"] < v["block"])
    print(f"[{out['label']}] payments {out['n']}  settled {out['n'] - missing}  never-settled {missing}  block-hash mismatches {mismatched}  receipts ahead of finalized {not_final}")
    if lat:
        lat.sort()
        print(f"  submit->first receipt: median {statistics.median(lat):.2f}s  p95 {lat[int(len(lat) * .95) - 1]:.2f}s  min {lat[0]:.2f}s  max {lat[-1]:.2f}s;  node spread median {statistics.median(spread) * 1000:.0f} ms")
    print(f"  final heights per node: {out['final_heights']}")


if __name__ == "__main__":
    a = sys.argv
    summarize(run(a[1], int(a[2]) if len(a) > 2 else 30, float(a[3]) if len(a) > 3 else 2.0, int(a[4]) if len(a) > 4 else 0))
