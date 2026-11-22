# Runbooks

Three runbooks cover the whole life of the lab. Use them in this order:

| Runbook | Use it to | Time |
|---|---|---|
| [build-runbook.md](build-runbook.md) | Build the fabric from an empty DSX Air account: topology, management server, SSH keys, Ansible, verification, GitHub | about 1 hour |
| [test-runbook.md](test-runbook.md) | Run the traffic, BFD, threshold, ceiling and RoCE tests, and check the results against the October 2026 reference numbers | 2-15 min per test |
| [demo-runbook.md](demo-runbook.md) | Prepare for and run the live interview demo: health check, Spine2 failure rehearsal, AI diagnosis | 20 min before, 5 min live |

What they rely on, all in this repository:

| Path | Role |
|---|---|
| `topology/ai-fabric-dsx-air.json` | The DSX Air topology to import: 13 devices, 40 links, out-of-band network |
| `inventory/` | The design: devices, groups, loopbacks, AS numbers, ports, BFD and RoCE settings |
| `templates/` | How the design becomes switch commands and server network files |
| `playbooks/` | Build (`underlay`, `servers`), verify (`verify*`), test (`traffic`, `threshold`, `ceiling`), collect state |
| `scripts/` | Traffic and sampling scripts, `summarize_results.py`, `fabric_doctor.py`, `demo.sh` |
| `results*/` | Recorded test results; the October 2026 runs are the reference |
| `reports/` | Fabric doctor reports and rehearsal summaries |

Every command in these runbooks runs on `oob-mgmt-server` as `ubuntu`, from
`~/ai-fabric`. Paste one line at a time: the DSX Air console scrambles
multi-line pastes.
