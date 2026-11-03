"""Live demos used in the video. Prints as it goes and writes nothing to results/.

Usage: python demo.py pay <validator 0-3 | testnet>     one payment, timed from submit to receipt
       python demo.py conflict [trial]                  same nonce, two payments, two validators
       python demo.py agree                             do all 4 validators hold the same chain?
"""
import contextlib, io, subprocess, sys, time
import harness as H

TO = "0x000000000000000000000000000000000000dEaD"


def pay(target):
    if target == "testnet":
        import testnet as T
        call, chain_check = T.rpc, 7295799
    else:
        url = H.NODES[int(target)]
        call, chain_check = (lambda m, *p: H.rpc(url, m, *p)), None
    chain = int(call("eth_chainId"), 16)
    assert chain_check in (None, chain), f"unexpected chain {chain}"
    nonce = int(call("eth_getTransactionCount", H.KEY["address"], "pending"), 16)
    base = int(call("eth_getBlockByNumber", "latest", False)["baseFeePerGas"], 16)
    raw = subprocess.check_output(["cast", "mktx", TO, "--value", "1", "--nonce", str(nonce), "--gas-limit", "21000", "--gas-price", str(base * 4),
                                   "--priority-gas-price", "0", "--chain", str(chain), "--private-key", H.KEY["private_key"]], text=True).strip()
    t0 = time.time()
    ack = call("eth_sendRawTransaction", raw)
    print(f"accepted, hash {ack[:18]}...  ({(time.time() - t0) * 1000:.0f} ms, no error)", flush=True)
    print("no receipt yet, polling...", flush=True)
    while time.time() - t0 < 240:
        try:
            r = call("eth_getTransactionReceipt", ack)
        except Exception:
            r = None
        if r:
            print(f"SETTLED in block {int(r['blockNumber'], 16)}, status {int(r['status'], 16)}, {time.time() - t0:.2f} s after submit", flush=True)
            return
        time.sleep(0.03)
    print("no receipt after 240 s", flush=True)


def conflict(i):
    import conflict as C
    with contextlib.redirect_stdout(io.StringIO()):  # the trial's own output is a raw JSON line
        r = C.trial(i)
    a, b = r["sent_to"]
    print(f"same sender, same nonce ({r['nonce']}), two different payments, sent at the same moment", flush=True)
    for side, v in (("A", a), ("B", b)):
        print(f"payment {side} to validator {v}: {'accepted, hash ' + r['acks'][side]['ack'][:18] + '...' if 'ack' in r['acks'][side] else r['acks'][side]['error']}")
    print(f"after {C.WAIT} s:")
    for side in "AB":
        got = [v for v in r[f"receipts_{side}"].values() if v]
        print(f"payment {side}: receipt on {len(got)} of 4 nodes" + (f", block {got[0]['block']}" if got else ""))
    print(f"balance moved by exactly one payment + fee on all nodes: {all(r['balance_delta_ok'].values())}")


def agree():
    import faults as F
    top = min(H.alive(u) for u in H.NODES)
    n = top - 3
    print(f"height {n} on each validator:")
    for i, u in enumerate(H.NODES):
        print(f"  validator {i}: {H.rpc(u, 'eth_getBlockByNumber', hex(n), False)['hash'][:22]}...")
    f = F.fork_check(1, top, 200)
    print(f"checked {f['heights_checked']} heights across all 4: {len(f['hash_mismatches'])} hash mismatches")
    print(f"distinct balances seen: {f['balance_values_seen']}, distinct nonces seen: {f['nonce_values_seen']}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    pay(sys.argv[2]) if cmd == "pay" else conflict(int(sys.argv[2]) if len(sys.argv) > 2 else 0) if cmd == "conflict" else agree()
