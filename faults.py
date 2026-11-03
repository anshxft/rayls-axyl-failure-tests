"""Fault-injection trials on the local 4-validator network (4 validators tolerate f = 1 failure).

B: crash one validator that neither receives our payments nor authors them; restart it.
C: crash the validator that authors our payment blocks (sender affinity); restart it.
D/E: crash two validators so quorum (3 of 4) is lost; submit payments anyway; restart; see what happens.
Usage: python faults.py B|C|DE [repeats]
"""
import json, os, subprocess, sys, threading, time
import harness as H

CWD = subprocess.check_output(["wsl.exe", "-d", "Ubuntu", "--cd", os.getcwd(), "--", "pwd"]).decode("utf-8", "ignore").replace("\x00", "").strip()


def ctl(*a):
    p = subprocess.run(["wsl.exe", "-d", "Ubuntu", "--", "bash", f"{CWD}/lab_ctl.sh", *map(str, a)], capture_output=True)
    return p.stdout.decode("utf-8", "ignore").replace("\x00", "").strip() or p.stderr.decode("utf-8", "ignore").strip()[:200]


def timeline(stop, out):
    while not stop.is_set():
        out.append((time.time(), [H.alive(u) for u in H.NODES]))
        time.sleep(0.25)


def stall_stats(tl):
    """Longest period in which no node's height increased."""
    best, last_t, top = 0.0, tl[0][0], -1
    for t, hs in tl:
        m = max((h for h in hs if h is not None), default=-1)
        if m > top:
            top, last_t = m, t
        best = max(best, t - last_t)
    return round(best, 2)


def wait_all_up(limit=180):
    t0 = time.time()
    while time.time() - t0 < limit:
        hs = [H.alive(u) for u in H.NODES]
        if all(h is not None for h in hs) and max(hs) - min(hs) <= 3:
            return round(time.time() - t0, 1), hs
        time.sleep(1)
    return None, [H.alive(u) for u in H.NODES]


def fork_check(lo, hi, samples=40):
    """Same height must have the same hash on every node, including blocks around the outage."""
    bad, seen = [], 0
    for n in range(lo, hi, max(1, (hi - lo) // samples)):
        hashes = {H.rpc(u, "eth_getBlockByNumber", hex(n), False)["hash"] for u in H.NODES}
        seen += 1
        if len(hashes) > 1:
            bad.append(n)
    bal = {H.rpc(u, "eth_getBalance", H.KEY["address"], "latest") for u in H.NODES}
    nonce = {H.rpc(u, "eth_getTransactionCount", H.KEY["address"], "latest") for u in H.NODES}
    return {"heights_checked": seen, "hash_mismatches": bad, "balance_values_seen": len(bal), "nonce_values_seen": len(nonce)}


def author_index():
    """Find which validator authors this sender's blocks, from the coinbase of a fresh payment's block."""
    out = H.run("_author_probe", 2, 1.5, submit=0, wait=20)
    rec = next(r for r in out["records"] if r["per_node"])
    block = next(iter(rec["per_node"].values()))["block"]
    miner = H.rpc(H.NODES[0], "eth_getBlockByNumber", hex(block), False)["miner"].lower()
    addrs = {l.split()[0]: l.split()[1].strip('"') for l in ctl("addr").splitlines() if len(l.split()) == 2}
    for idx, a in addrs.items():
        if a.lower() == miner:
            return int(idx), miner, addrs
    raise RuntimeError(f"coinbase {miner} not among {addrs}")


def trial(label, kill, submit, n, kill_at, restart_at, wait):
    stop, tl = threading.Event(), []
    th = threading.Thread(target=timeline, args=(stop, tl), daemon=True); th.start()
    start_h = H.alive(H.NODES[submit])
    hooks = {kill_at: lambda: [ctl("kill", k) for k in kill], restart_at: lambda: [ctl("start", k) for k in kill]}
    out = H.run(label, n, 2.0, submit=submit, wait=wait, hooks=hooks)
    recovered_s, hs = wait_all_up()
    stop.set(); th.join()
    t_kill, t_restart = out["events"][0]["t"], out["events"][1]["t"]
    rows = []
    for r in out["records"]:
        got = r["per_node"]
        rows.append({"i": r["i"], "submit_error": r.get("submit_error"), "t_submit": r["t_submit"],
                     "latency": round(min(v["t"] for v in got.values()) - r["t_submit"], 3) if got else None,
                     "nodes_with_receipt": len(got), "statuses": sorted({v["status"] for v in got.values()})})
    phase = lambda r: "before" if r["t_submit"] < t_kill else "during" if r["t_submit"] < t_restart else "after"
    summary = {"label": label, "killed": kill, "submit_node": submit, "longest_chain_stall_s": stall_stats(tl), "resynced_after_s": recovered_s, "heights_after": hs,
               "chain_height_at_kill_vs_restart": [next((max(h for h in x[1] if h is not None) for x in tl if x[0] >= t), None) for t in (t_kill, t_restart)],
               "fork_check": fork_check(start_h, min(h for h in hs if h is not None))}
    for ph in ("before", "during", "after"):
        sel = [r for r in rows if phase(r) == ph]
        lat = sorted(r["latency"] for r in sel if r["latency"] is not None)
        summary[ph] = {"payments": len(sel), "settled": len(lat), "rejected_at_submit": sum(1 for r in sel if r["submit_error"]),
                       "median_s": lat[len(lat) // 2] if lat else None, "max_s": lat[-1] if lat else None, "failed_status": sum(1 for r in sel if 0 in r["statuses"])}
    out.update(summary=summary, height_timeline=tl, rows=rows)
    json.dump(out, open(f"results/{label}.json", "w"), indent=1)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    kind, reps = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for r in range(int(os.environ.get("START", 1)), reps + 1):
        ctl("reset", H.KEY["address"])  # fresh genesis per trial: one trial's damage must not leak into the next
        time.sleep(60)
        wait_all_up()
        a, miner, addrs = author_index()
        print(f"author of our payments: validator {a} ({miner})", flush=True)
        others = [i for i in range(4) if i != a]
        if kind == "B":   # submit to one non-author, crash a different non-author
            trial(f"B_one_down_run{r}", [others[1]], others[0], 40, 10, 30, 60)
        elif kind == "C":  # crash the author itself
            trial(f"C_author_down_run{r}", [a], others[0], 40, 10, 30, 60)
        elif kind == "DE":  # lose quorum, keep paying, then recover
            trial(f"DE_quorum_lost_run{r}", [a, others[1]], others[0], 40, 10, 25, 240)
