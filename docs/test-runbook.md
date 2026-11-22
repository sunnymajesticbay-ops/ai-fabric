# Test runbook

Five tests. Each is a playbook run plus one summary command; the two
comparisons run a test twice, once each way. Every test writes
CSV files to a results folder you name, and `scripts/summarize_results.py`
turns them into the numbers to check against the reference results from
October 2026 below.

| Test | Playbook | Time | Answers |
|---|---|---|---|
| 1. Traffic and spine failure | `traffic.yml` | 5 min | Does traffic spread across the spines, and what happens when one fails? |
| 2. BFD comparison | `traffic.yml` twice | 15 min | How much does BFD shorten the outage? |
| 3. Threshold | `threshold.yml` | 4 min | Where does the fabric saturate, and is the limit the switches? |
| 4. Ceiling | `ceiling.yml` | 2 min | How fast is one link, one path, and five rails at once? |
| 5. RoCE comparison | `ceiling.yml` twice | 10 min | Does RoCE lossless mode change throughput here? |

## Before any test

1. The fabric must pass the build checks. Run these one at a time; every line
   should pass (see [build-runbook.md](build-runbook.md), steps 6 and 7):
   ```
   cd ~/ai-fabric
   ansible-playbook playbooks/verify.yml
   ansible-playbook playbooks/verify-servers.yml
   ```
2. On a new build, install the traffic generator once. `traffic.yml` installs
   it, but `threshold.yml` and `ceiling.yml` assume it is already there:
   ```
   ansible servers -b -m shell -a "apt-get update && apt-get install -y iperf3"
   ```
3. **Always give a new results folder.** Without `-e ..._dir=...`, the
   playbooks write into `results/`, `results-threshold/` and
   `results-ceiling/`, overwriting the recorded October baselines. The
   commands below add today's date to each folder name.
4. Run one test at a time. Tests share the servers' iperf3 listeners.

## Test 1: Traffic and spine failure

Generates rate-limited iperf3 flows (4 Mbit/s each) in six phases, and records
every switch port's byte counters every 2 seconds:

| Phase | Length | Traffic |
|---|---|---|
| Idle | 20 s | none |
| Same rail | 40 s | 20 flows, each staying on its own leaf |
| Idle | 15 s | none |
| Cross rail, light | 40 s | 20 flows, each crossing a spine |
| Cross rail, heavy | 120 s | 60 flows; 35 s in, Spine2's five fabric ports are shut for 30 s, then restored |
| Idle | 20 s | none |

Run:

```
ansible-playbook playbooks/traffic.yml -e results_dir=$PWD/results-traffic-$(date +%F)
```

The playbook's last messages should show, for each server, `5 of 5 flows
completed` (same rail and light) and `15 of 15 flows completed` (heavy), then
`... samples from 9 switches`.

Check the results against the recorded run with BFD:

```
python3 scripts/summarize_results.py results-bfd results-traffic-$(date +%F)
```

Reference results:

| Measure | Before BFD (`results`) | With BFD (`results-bfd`) | A good run |
|---|---|---|---|
| Same-rail delivered | 85 Mbit/s | 85 Mbit/s | about 85 |
| Cross-rail heavy delivered | 255 Mbit/s | 255 Mbit/s | about 255 |
| Spine shares, heavy phase | 22 / 28 / 23 / 27% | 22 / 25 / 36 / 17% | each spine 15-35% |
| Lowest delivered during the failure | 144 Mbit/s | 241 Mbit/s | above 220 with BFD |
| Worst drop | 43% | 6% | under 10% with BFD |
| Time below 90% of normal | 10 s | 0 s | 0-2 s with BFD |
| Traffic held back | 780 Mbit | 94 Mbit | under 150 with BFD |

Spine shares vary run to run because ECMP places whole flows, not packets, on a
spine. "Time below 90%" counts the 2-second samples where delivered traffic
was under 90% of normal; the slides quote "about 12 s" for the full span from
failure to complete recovery.

Afterwards, confirm Spine2 is back: `ansible-playbook playbooks/verify.yml`
should show `5 of 5` on Spine2. If not, run `scripts/demo.sh restore Spine2`.

## Test 2: BFD comparison

Every build has BFD on. To repeat the before-and-after comparison, run Test 1
with BFD off, then on. One line at a time:

1. Turn BFD off on every switch:
   ```
   ansible switches -m shell -a "nv set router bfd state disabled && nv config apply -y"
   ansible-playbook playbooks/verify.yml
   ```
   Expected: all BGP sessions established and `0 of N BFD sessions up`.
2. Run the traffic test without BFD:
   ```
   ansible-playbook playbooks/traffic.yml -e results_dir=$PWD/results-nobfd-$(date +%F)
   ```
3. Turn BFD back on (re-applying the template restores it) and check:
   ```
   ansible-playbook playbooks/underlay.yml
   ansible-playbook playbooks/verify.yml
   ```
   Expected: `5 of 5` and `4 of 4` BFD sessions up again.
4. Run the traffic test with BFD:
   ```
   ansible-playbook playbooks/traffic.yml -e results_dir=$PWD/results-bfd-$(date +%F)
   ```
5. Compare:
   ```
   python3 scripts/summarize_results.py results-nobfd-$(date +%F) results-bfd-$(date +%F)
   ```

Expected: a worst drop of about 43% without BFD and about 6% with it, matching
the reference table in Test 1. Without BFD the leaves only notice the failure
when Spine2's BGP keepalives stop and the 9-second hold timer expires: in DSX
Air, the leaves' side of each link stays up when Spine2 shuts its own ports.
BFD (300 ms x 3) detects it in under a second.

## Test 3: Threshold

Raises the load in six steps on 60 cross-rail flows: 4, 20, 50, 100, 200 and
330 Mbit/s per flow (0.24 to 19.8 Gbit/s requested), 20 seconds each with 8
seconds of rest. Every 2 seconds it records port bytes and drops on all 13
devices, and CPU time on all of them.

```
ansible-playbook playbooks/threshold.yml -e threshold_dir=$PWD/results-threshold-$(date +%F)
python3 scripts/summarize_results.py results-threshold results-threshold-$(date +%F)
```

The playbook should end with `... port samples and ... CPU samples from 13 nodes`.

Reference results (`results-threshold`):

| Per flow | Requested | Delivered | Busiest leaf CPU | Busiest spine CPU | Busiest server CPU |
|---|---|---|---|---|---|
| 4 Mbit/s | 0.24 Gbit/s | 0.26 Gbit/s | 5% | 1% | 100% |
| 20 Mbit/s | 1.20 | 1.28 | 16% | 3% | 100% |
| 50 Mbit/s | 3.00 | 1.90 | 28% | 4% | 94% |
| 100 Mbit/s | 6.00 | 1.96 | 31% | 4% | 54% |
| 200 Mbit/s | 12.00 | 1.91 | 29% | 4% | 47% |
| 330 Mbit/s | 19.80 | 1.97 | 30% | 4% | 55% |

Packets dropped on all ports: **0**.

How to read it: delivered traffic levels off at about 1.9 Gbit/s once 3 Gbit/s
is requested, with switch CPU never above about 30% and no drops. The ceiling
belongs to the simulator's virtual links, not to the switches. Server CPU at
100% in the first two steps is iperf3 pacing many slow flows, not a limit.

## Test 4: Ceiling

Unthrottled iperf3 from Server1 to Server2, 15 seconds per test (the first 2
seconds are left out as warm-up):

| Test | Path |
|---|---|
| A | One flow, same rail: Server1 eth1, Leaf1, Server2 eth1 |
| B | One flow, cross rail: Server1 eth1, Leaf1, a spine, Leaf2, Server2 eth2 |
| C | Four parallel streams on the same single link as A |
| D | Five flows at once, one per rail, each staying on its leaf |
| E | Five flows at once, one per rail, each crossing a spine |

```
ansible-playbook playbooks/ceiling.yml -e ceiling_dir=$PWD/results-ceiling-$(date +%F)
python3 scripts/summarize_results.py results-ceiling-bfd results-ceiling-$(date +%F)
```

The playbook prints the summary lines itself when it finishes.

Reference results (Mbit/s, with TCP retransmits in brackets):

| Test | 12 Oct baseline | 13 Oct with BFD | 13 Oct with BFD and RoCE |
|---|---|---|---|
| A | 576 | 656 (705) | 650 (729) |
| B | 543 | 638 (563) | 584 (620) |
| C | 557 | 642 (7,586) | 658 (7,941) |
| D | 1,450 | 1,659 (5,228) | 1,687 (4,704) |
| E | 1,228 | 1,351 (2,313) | 1,445 (2,642) |

How to read it: one link carries about 550-650 Mbit/s depending on the day, so
compare runs made in the same session. Four streams on one link (C) move no
more data than one; they only multiply retransmits about tenfold, a sign the
link is full. Five rails in parallel reach about 1.2-1.7 Gbit/s.

## Test 5: RoCE comparison

Every build has RoCE lossless mode on (`roce_enabled: true`). To compare
throughput with and without it, one line at a time:

1. Turn RoCE off and check:
   ```
   ansible switches -m shell -a "nv unset qos roce && nv config apply -y"
   ansible-playbook playbooks/verify-roce.yml
   ```
   Expected: `RoCE NOT found` on every switch.
2. Run the ceiling test without RoCE:
   ```
   ansible-playbook playbooks/ceiling.yml -e ceiling_dir=$PWD/results-ceiling-noroce-$(date +%F)
   ```
3. Turn RoCE back on and check:
   ```
   ansible-playbook playbooks/underlay.yml
   ansible-playbook playbooks/verify-roce.yml
   ```
   Expected: `RoCE lossless is configured` on all 9 switches.
4. Run the ceiling test with RoCE, and compare:
   ```
   ansible-playbook playbooks/ceiling.yml -e ceiling_dir=$PWD/results-ceiling-roce-$(date +%F)
   python3 scripts/summarize_results.py results-ceiling-noroce-$(date +%F) results-ceiling-roce-$(date +%F)
   ```

Expected: no consistent difference. In October the change ranged from -9% to
+7%, within normal run-to-run variation. That is the expected result in this
lab, for three reasons: Cumulus VX forwards in software and doesn't support
QoS buffer management or packet marking, the test traffic is TCP rather than
RDMA, and the losses come from full links, which lossless transport can't fix.

## Save the results

```
scripts/demo.sh sync "Test results $(date +%F)"
```

The new results folders are committed and pushed with everything else.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `iperf3: command not found`, or `0 of 15 flows completed` | iperf3 isn't installed on the servers | Run step 2 of "Before any test" |
| Fewer flows completed than expected, `Connection refused` | An iperf3 listener stopped | Re-run the test; each playbook restarts missing listeners |
| Spine2 still down after an interrupted Test 1 | The playbook stopped before its restore step | `scripts/demo.sh restore Spine2` |
| A test was interrupted and the next one records odd data | The previous sampler is still running (it stops by itself after 10-15 min) | `ansible switches:servers -m shell -a "pkill -f '[s]ampler' \|\| true"`, then re-run |
| `No route to host` or unreachable switches | The simulation slept and the management server has stale ARP entries | `sudo ip neigh flush all` |
| Results 10-15% away from the reference | Normal day-to-day variation in the simulator | Compare runs made in the same session |
| `summarize_results.py`: `no counters.csv, ports.csv or summary.csv found` | Wrong folder, or the playbook stopped before collecting | Check the folder name with `ls`; re-run the test |
| The October baselines changed | A test ran without `-e ..._dir=...` | `git checkout -- results results-threshold results-ceiling` restores them |
