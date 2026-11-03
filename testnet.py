"""Test G: real signed payments on the public Rayls Testnet, timed from submit to receipt.

Network round trip to the RPC is measured separately and reported, because it is part of what a client sees.
Usage: python testnet.py <run_label> [payments] [gap_seconds]
"""
import json, os, statistics, subprocess, sys, threading, time, urllib.request
import harness as H

RPC = "https://testnet-rpc.rayls.com/"
TO = "0x000000000000000000000000000000000000dEaD"
ADDR = H.KEY["address"]


def rpc(m, *p, timeout=10):
    req = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": m, "params": list(p)}).encode(), {"Content-Type": "application/json", "User-Agent": "axyl-lab/1"})
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]


def run(label, n, gap):
    chain = int(rpc("eth_chainId"), 16)
    assert chain == 7295799, f"unexpected chain {chain}"  # never run this against anything but the testnet
    nonce = int(rpc("eth_getTransactionCount", ADDR, "pending"), 16)
    base = int(rpc("eth_getBlockByNumber", "latest", False)["baseFeePerGas"], 16)
    signed = []
    for i in range(n):
        raw = subprocess.check_output(["cast", "mktx", TO, "--value", "1", "--nonce", str(nonce + i), "--gas-limit", "21000", "--gas-price", str(base * 2),
                                       "--priority-gas-price", "0", "--chain", str(chain), "--private-key", H.KEY["private_key"]], text=True).strip()
        signed.append((raw, subprocess.check_output(["cast", "keccak", raw], text=True).strip()))
    rtts = []
    for _ in range(20):
        t = time.time(); rpc("eth_blockNumber"); rtts.append((time.time() - t) * 1000)

    heads, stop = [], threading.Event()
    def watch_head():
        seen = None
        while not stop.is_set():
            try:
                h = int(rpc("eth_blockNumber"), 16)
                if h != seen:
                    heads.append((time.time(), h)); seen = h
            except Exception:
                pass
            time.sleep(0.05)
    threading.Thread(target=watch_head, daemon=True).start()

    records = []
    for i, (raw, h) in enumerate(signed):
        rec = {"i": i, "hash": h, "t_submit": time.time()}
        try:
            rpc("eth_sendRawTransaction", raw); rec["t_ack"] = time.time()
        except Exception as e:
            rec["error"] = str(e)[:200]
        deadline = rec["t_submit"] + 60
        while "error" not in rec and time.time() < deadline:
            try:
                r = rpc("eth_getTransactionReceipt", h)
            except Exception:
                r = None
            if r:
                rec["t_receipt"] = time.time(); rec["block"] = int(r["blockNumber"], 16); rec["status"] = int(r["status"], 16)
                try:
                    rec["finalized_at_receipt"] = int(rpc("eth_getBlockByNumber", "finalized", False)["number"], 16)
                except Exception:
                    rec["finalized_at_receipt"] = None
                break
            time.sleep(0.03)
        records.append(rec)
        time.sleep(gap)
    stop.set()
    os.makedirs("results", exist_ok=True)
    json.dump({"label": label, "chain": chain, "rpc": RPC, "rtt_ms": rtts, "records": records, "heads": heads}, open(f"results/{label}.json", "w"), indent=1)

    lat = sorted(r["t_receipt"] - r["t_submit"] for r in records if "t_receipt" in r)
    gaps = [b[0] - a[0] for a, b in zip(heads, heads[1:])]
    print(f"[{label}] sent {n}  settled {len(lat)}  failed-status {sum(1 for r in records if r.get('status') == 0)}  errors {sum(1 for r in records if 'error' in r)}")
    if lat:
        print(f"  submit->receipt: median {statistics.median(lat):.2f}s  p95 {lat[max(int(len(lat) * .95) - 1, 0)]:.2f}s  min {lat[0]:.2f}s  max {lat[-1]:.2f}s;  under 1 s: {sum(1 for x in lat if x < 1)}/{len(lat)}")
    print(f"  rpc round trip median {statistics.median(rtts):.0f} ms;  new-head gap median {statistics.median(gaps) if gaps else 0:.2f}s;  receipts ahead of finalized: {sum(1 for r in records if r.get('finalized_at_receipt') is not None and r['finalized_at_receipt'] < r['block'])}")


if __name__ == "__main__":
    a = sys.argv
    run(a[1], int(a[2]) if len(a) > 2 else 50, float(a[3]) if len(a) > 3 else 2.0)
