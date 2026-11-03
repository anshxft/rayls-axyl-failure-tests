"""Does a restarted validator diverge? Fresh network per trial, one controlled restart each.

Conditions: crash (SIGKILL) or graceful stop (SIGTERM), restart after a short or long downtime.
Pass = after resync the restarted node matches the others at a common height and its rounds keep rising.
Usage: python repro.py [repeats]
"""
import json, os, sys, time
import faults as F
import harness as H

ADDR = H.KEY["address"]
VICTIM = 2
CONDITIONS = [("kill", int(x)) for x in os.environ["DOWNTIMES"].split(",")] if os.environ.get("DOWNTIMES") else [("kill", 10), ("kill", 120), ("term", 10)]
RUN_BEFORE, OBSERVE_AFTER = 180, 120


def block(u, n):
    return H.rpc(u, "eth_getBlockByNumber", hex(n), False, timeout=10)


def fresh():
    print(" reset:", F.ctl("reset", ADDR)[-60:], flush=True)
    t0 = time.time()
    while time.time() - t0 < 240:
        hs = [H.alive(u) for u in H.NODES]
        if all(h and h > 5 for h in hs):
            return
        time.sleep(3)
    raise RuntimeError("fresh network did not come up")


def compare(ref, victim):
    top_r, top_v = H.alive(ref), H.alive(victim)
    res = {"ref_height": top_r, "victim_height": top_v}
    if top_v is None:
        res["verdict"] = "victim-down"
        return res
    top = min(top_r, top_v)
    same = block(ref, top)["hash"] == block(victim, top)["hash"]
    res["same_hash_at_common_height"] = same
    if not same:
        lo, hi = 1, top
        while lo < hi:
            mid = (lo + hi) // 2
            if block(ref, mid)["hash"] == block(victim, mid)["hash"]:
                lo = mid + 1
            else:
                hi = mid
        rnd = lambda u: int(block(u, lo)["nonce"], 16) & 0xFFFFFFFF
        res.update(first_diff=lo, ref_round=rnd(ref), victim_round=rnd(victim))
    res["finalized"] = [int(H.rpc(u, "eth_getBlockByNumber", "finalized", False)["number"], 16) for u in (ref, victim)]
    res["verdict"] = "match" if same else "DIVERGED"
    return res


os.makedirs("results", exist_ok=True)
reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2
out = []
for rep in range(1, reps + 1):
    for how, downtime in CONDITIONS:
        label = f"R_{how}_{downtime}s_run{rep}"
        fresh()
        time.sleep(RUN_BEFORE)
        ref, victim = H.NODES[1], H.NODES[VICTIM]
        h_before = H.alive(ref)
        F.ctl(how, VICTIM)
        time.sleep(downtime)
        h_restart = H.alive(ref)
        F.ctl("start", VICTIM)
        time.sleep(OBSERVE_AFTER)
        r = {"label": label, "how": how, "downtime_s": downtime, "height_at_stop": h_before, "height_at_restart": h_restart, **compare(ref, victim)}
        r["log"] = F.ctl("mismatches", VICTIM)
        out.append(r)
        json.dump(out, open(os.environ.get("OUT", "results/restart_repro.json"), "w"), indent=1)
        print(json.dumps(r), flush=True)
