# If Rayls validators fail mid-payment, does the payment settle, stall, or fork?

Independent test of Axyl, the Rayls Public Chain consensus client. Validators were crashed during live payments on a local network, and real payments were timed on the public testnet. Not affiliated with Rayls.

**Short answer on the tested setup:** it stalls rather than forks. With one of four validators down, payments kept settling. With two down, the chain stopped, then all pending payments settled after recovery. A returned transaction hash did not mean settled.

Read [CLAIMS_AND_LIMITS.md](CLAIMS_AND_LIMITS.md) before quoting any number.

## Check the results without running a network

```bash
python check_results.py   # recomputes every number from results/ and fails on a broken invariant
python test_tamper.py     # changes the data 11 ways and confirms the checker rejects each one
sha256sum -c SHA256SUMS.txt
```

Needs only Python 3.

## Reproduce

Requires Linux or WSL2, Rust, and [Foundry](https://getfoundry.sh) `cast`. The exact Axyl commit is in `AXYL_COMMIT.txt`. Create a throwaway key, never a real one, with `cast wallet new --json > lab/testkey.json`.

| Script | Test |
|---|---|
| `wsl_build.sh`, `lab_start.sh` | Build Axyl, start 4 validators |
| `harness.py A_control_run1 30 2` | A: no failure |
| `faults.py B 3` | B: crash one validator |
| `faults.py C 3` | C: crash the validator authoring our blocks |
| `faults.py DE 3` | D/E: crash two, lose quorum, recover |
| `conflict.py 24` | F: same-nonce payments sent to two validators |
| `repro.py` | Restart a validator after 10, 120 or 600 s |
| `testnet.py G_testnet_run1 50 2` | G: real testnet payments (needs faucet tokens) |
| `mainnet/verify_axyl.py` | Read-only mainnet measurements |
| `demo.py` | The live demos shown in the video. Writes nothing to `results/` |
| `video/` | Scripts that recorded and assembled the video |

Scripts run from Windows and call into WSL. Paths may need adjusting elsewhere.

## Layout

`results/` raw data for every counted run · `mainnet/` read-only chain data · `figures/` charts built from `results/` · `docs_failures/` discarded runs and why
