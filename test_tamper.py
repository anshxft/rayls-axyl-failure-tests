"""The checker must reject altered data. Each case changes one thing in a copy of real results.

Usage: python test_tamper.py    (exits 1 if any altered copy passes)
"""
import copy, json, os, sys
import check_results as C

R = C.ROOT
run = json.load(open(os.path.join(R, "DE_quorum_lost_run1.json")))
conflict = json.load(open(os.path.join(R, "F_conflict.json")))
restart = json.load(open(os.path.join(R, "restart_repro.json")))
testnet = json.load(open(os.path.join(R, "G_testnet_run1.json")))


def first_node(rec):
    return next(iter(rec["per_node"].values()))


def t_status(d):
    first_node(d["records"][12])["status"] = 0
def t_hash(d):
    first_node(d["records"][12])["block_hash"] = "0x" + "ab" * 32
def t_missing(d):
    d["records"][12]["per_node"].popitem()
def t_final(d):
    v = first_node(d["records"][12]); v["finalized_at_receipt"] = v["block"] - 5
def t_fork(d):
    d["summary"]["fork_check"]["hash_mismatches"] = [123]
def t_nonce(d):
    d["summary"]["fork_check"]["nonce_values_seen"] = 2
def f_both(d):
    d[3]["winner"] = "both"
def f_loser(d):
    r = d[3]; side = "receipts_B" if r["winner"] == "A" else "receipts_A"; r[side]["8545"] = {"block": 1}
def f_balance(d):
    k = next(iter(d[3]["balance_delta_ok"])); d[3]["balance_delta_ok"][k] = False
def r_diverged(d):
    d[1]["verdict"] = "DIVERGED"
def g_status(d):
    d["records"][4]["status"] = 0


CASES = [("payment marked failed", C.check_fault_run, run, t_status), ("one node's block hash changed", C.check_fault_run, run, t_hash), ("one node's receipt removed", C.check_fault_run, run, t_missing),
         ("receipt ahead of finalized", C.check_fault_run, run, t_final), ("fork injected", C.check_fault_run, run, t_fork), ("nonce disagreement", C.check_fault_run, run, t_nonce),
         ("double spend injected", C.check_conflict, conflict, f_both), ("loser given a receipt", C.check_conflict, conflict, f_loser), ("balance altered", C.check_conflict, conflict, f_balance),
         ("restart marked diverged", C.check_restart, restart, r_diverged), ("testnet payment unsettled", C.check_testnet, testnet, g_status)]

fails = 0
assert not C.check_fault_run(run) and not C.check_conflict(conflict) and not C.check_restart(restart) and not C.check_testnet(testnet), "unaltered data must pass"
for name, check, data, tamper in CASES:
    d = copy.deepcopy(data)
    tamper(d)
    caught = bool(check(d))
    fails += not caught
    print(f"{'rejected' if caught else 'MISSED  '}  {name}")
print(f"{len(CASES) - fails}/{len(CASES)} altered copies rejected")
sys.exit(1 if fails else 0)
