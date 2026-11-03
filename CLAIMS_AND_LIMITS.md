# Claims and limits

## What the data supports

Local network: Axyl v1.5.1 built from source, 4 validators on one laptop (WSL2), default local config, fresh genesis per fault trial.

- No failure: 90/90 payments settled, median 1.05 s.
- One validator crashed (including the one authoring our blocks): 240/240 settled across 6 runs. Longest chain pause 2.58 s.
- Two of four crashed, so quorum was lost: the chain stopped in all 3 runs until the validators returned (61.8 to 67.5 s, which is how long we kept them down).
- During that stop, nodes accepted all 45 payments without an error. All 45 settled after recovery, 8 to 69 s after submission.
- No block-hash, balance or nonce disagreement in any counted fault run.
- Same-nonce conflict: in 24/24 trials one payment won. No double spend. Both submissions returned a hash, the loser had no receipt on any node after 20 s, and the balance moved by exactly one payment plus its fee.
- Restart: 8/8 trials had the same block hash as the network at their common height, after 10, 120 or 600 s of downtime. In one 600 s trial the node was still catching up when checked (1,125 vs 1,599), so that trial confirms agreement only up to height 1,125.

Public Rayls Testnet: 150/150 payments settled, median 2.44 s from submit to receipt, 0 under 1 s. RPC round trip was about 0.40 s, so about 2.05 s after subtracting one round trip. New blocks appeared every 0.48 s (median).

Mainnet, read-only: finalized equalled latest in every sample. Average block time 1.235 s over complete epochs. See `mainnet/`.

## What it does not show

- Local timings are not mainnet timings. Four nodes on one machine have almost no network delay and share one CPU.
- We did not send payments on mainnet, so mainnet submit-to-receipt time is unmeasured.
- Testnet latency was measured from one location through one public RPC. Polling adds some delay. Subtracting one round trip is an approximation.
- A 60-second outage says nothing about outages of hours, or about pending transactions being evicted from a pool.
- Crashes only. No Byzantine behaviour, network partitions or disk corruption were tested.
- "No receipt after 20 s" is the observation window, not proof that a receipt could never appear.
- One restarted validator diverged from the network early in testing, in a run that also had the script failure listed below. It did not recur in the 8 restart trials and is unexplained. It was reported privately to the Rayls maintainers, so its details are not in this repo.
- Small samples: 3 runs per fault condition and 24 conflict trials. These are not reliability estimates.
- Block authorship on mainnet is sampled every 2,000th block. Why one validator authors so few blocks is inference, not confirmed.

## Mistakes and failed runs

Kept in `docs_failures/` and excluded from the numbers above.

1. A timer started before a health check in the harness, adding about 8 s to every payment. All latency data from those runs was discarded and Test A was rerun.
2. A restart script failed because `cargo` was not on PATH inside tmux, which left a validator down for much longer than planned.
3. The default local setup would not start: genesis used chain ID 487 while `.env.example` selects `devnet` (503). We set `RAYLS_NETWORK="local"`.
4. An early quorum formula in the mainnet script was wrong and was corrected to floor(2n/3)+1.
