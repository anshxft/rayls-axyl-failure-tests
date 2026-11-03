"""Recompute every headline number from the raw result files, and fail if the data breaks an invariant.

Usage: python check_results.py     (writes results/SUMMARY.json, exits 1 on any problem)
"""
import glob, json, os, statistics as S, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load(pattern):
    return [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, pattern)))]


def latency(rec):
    return min(v["t"] for v in rec["per_node"].values()) - rec["t_submit"] if rec["per_node"] else None


def check_payment_run(run):
    """Every payment settled, succeeded, on all 4 nodes, in the same block, and never ahead of finalized."""
    bad = []
    for r in run["records"]:
        got = r["per_node"]
        # a crashed validator cannot serve receipts; every other node must have one
        killed = (run.get("summary") or {}).get("killed", [])
        missing = [p for i, p in enumerate((8545, 8544, 8543, 8542)) if i not in killed and not any(u.endswith(str(p)) for u in got)]
        if missing:
            bad.append(f"{run['label']} #{r['i']}: no receipt on live node(s) {missing}")
        if any(v["status"] != 1 for v in got.values()):
            bad.append(f"{run['label']} #{r['i']}: failed status")
        if len({v["block_hash"] for v in got.values()}) > 1:
            bad.append(f"{run['label']} #{r['i']}: nodes disagree on block hash")
        if any(v["finalized_at_receipt"] is not None and v["finalized_at_receipt"] < v["block"] for v in got.values()):
            bad.append(f"{run['label']} #{r['i']}: receipt ahead of finalized")
    return bad


def check_fault_run(run):
    bad = check_payment_run(run)
    fc = run["summary"]["fork_check"]
    if fc["hash_mismatches"]:
        bad.append(f"{run['label']}: block hash mismatches {fc['hash_mismatches'][:3]}")
    if fc["balance_values_seen"] != 1 or fc["nonce_values_seen"] != 1:
        bad.append(f"{run['label']}: nodes disagree on balance or nonce")
    return bad


def check_conflict(rows):
    bad = []
    for r in rows:
        if r["winner"] not in ("A", "B"):
            bad.append(f"F trial {r['trial']}: winner={r['winner']}")
        loser = r["receipts_B"] if r["winner"] == "A" else r["receipts_A"]
        if any(loser.values()):
            bad.append(f"F trial {r['trial']}: loser has a receipt")
        if not all(r["balance_delta_ok"].values()):
            bad.append(f"F trial {r['trial']}: balance moved by more than one payment + fee")
        if not r["same_block_hash"] or r["nodes_with_winner_receipt"] != 4:
            bad.append(f"F trial {r['trial']}: nodes disagree")
        if len(set(r["nonce_after"].values())) != 1:
            bad.append(f"F trial {r['trial']}: nodes disagree on nonce")
    return bad


def check_testnet(run):
    return [f"{run['label']} #{r['i']}: not settled" for r in run["records"] if r.get("status") != 1]


def check_restart(rows):
    return [f"{r['label']}: {r['verdict']}" for r in rows if r["verdict"] != "match"]


def check_all():
    A, B, C, DE = load("A_control_run*.json"), load("B_one_down_run*.json"), load("C_author_down_run*.json"), load("DE_quorum_lost_run*.json")
    F = load("F_conflict.json")[0]
    G = load("G_testnet_run*.json")
    R = load("restart_repro.json")[0] + load("restart_long.json")[0]
    bad = [p for x in A for p in check_payment_run(x)]
    for x in B + C + DE:
        bad += check_fault_run(x)
    bad += check_conflict(F) + check_restart(R)
    for x in G:
        bad += check_testnet(x)
    a_lat = [latency(r) for x in A for r in x["records"]]
    phase = lambda runs, p: {"payments": sum(x["summary"][p]["payments"] for x in runs), "settled": sum(x["summary"][p]["settled"] for x in runs), "rejected_at_submit": sum(x["summary"][p]["rejected_at_submit"] for x in runs),
                             "median_of_run_medians_s": S.median(x["summary"][p]["median_s"] for x in runs), "max_s": max(x["summary"][p]["max_s"] for x in runs)}
    g_lat = sorted(r["t_receipt"] - r["t_submit"] for x in G for r in x["records"])
    rtt = S.median(v for x in G for v in x["rtt_ms"]) / 1000
    heads = [b[0] - a[0] for x in G for a, b in zip(x["heads"], x["heads"][1:])]
    summary = {
        "A_control": {"payments": len(a_lat), "settled": sum(1 for x in a_lat if x is not None), "median_s": round(S.median(a_lat), 3)},
        "B_one_down": {"runs": len(B), "longest_stall_s": max(x["summary"]["longest_chain_stall_s"] for x in B), **{p: phase(B, p) for p in ("before", "during", "after")}},
        "C_author_down": {"runs": len(C), "longest_stall_s": max(x["summary"]["longest_chain_stall_s"] for x in C), **{p: phase(C, p) for p in ("before", "during", "after")}},
        "DE_quorum_lost": {"runs": len(DE), "stalls_s": [x["summary"]["longest_chain_stall_s"] for x in DE], "height_at_kill_vs_restart": [x["summary"]["chain_height_at_kill_vs_restart"] for x in DE], **{p: phase(DE, p) for p in ("before", "during", "after")}},
        "F_conflict": {"trials": len(F), "A": sum(r["winner"] == "A" for r in F), "B": sum(r["winner"] == "B" for r in F), "both": sum(r["winner"] == "both" for r in F),
                       "both_acked_at_submit": sum(all("ack" in v for v in r["acks"].values()) for r in F), "balance_exact": sum(all(r["balance_delta_ok"].values()) for r in F)},
        "G_testnet": {"payments": len(g_lat), "settled": sum(1 for x in G for r in x["records"] if r.get("status") == 1), "median_s": round(S.median(g_lat), 2), "p95_s": round(g_lat[int(len(g_lat) * .95)], 2), "min_s": round(g_lat[0], 2), "max_s": round(g_lat[-1], 2),
                      "under_1s": sum(x < 1 for x in g_lat), "rpc_rtt_median_s": round(rtt, 3), "median_minus_one_rtt_s": round(S.median(g_lat) - rtt, 2), "new_head_gap_median_s": round(S.median(heads), 2)},
        "restart": {"trials": len(R), "match": sum(r["verdict"] == "match" for r in R), "downtimes_s": sorted({r["downtime_s"] for r in R})},
    }
    return summary, bad


if __name__ == "__main__":
    summary, bad = check_all()
    json.dump(summary, open(os.path.join(ROOT, "SUMMARY.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))
    print("\nPROBLEMS:" if bad else "\nAll invariants hold.")
    for b in bad:
        print(" ", b)
    sys.exit(1 if bad else 0)
