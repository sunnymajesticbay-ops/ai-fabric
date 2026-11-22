# Build runbook

This runbook takes an empty NVIDIA DSX Air account to a fully configured,
verified AI fabric with everything saved in GitHub, in about an hour. Only
steps 1 to 4 are manual; Ansible configures the 9 switches and 4 servers.

| Step | What happens | Time |
|---|---|---|
| 1 | Create the simulation in DSX Air | 10 min |
| 2 | Prepare the management server | 5 min |
| 3 | First login and SSH keys on all 13 devices | 15 min |
| 4 | Clone this repository onto the management server | 5 min |
| 5 | Check that Ansible reaches every device | 2 min |
| 6 | Configure and verify the switches | 5 min |
| 7 | Configure and verify the servers | 3 min |
| 8 | Save the result to GitHub | 2 min |
| 9 | Optional: set up AI troubleshooting | 5 min |

Conventions:

- Every command runs on `oob-mgmt-server` as user `ubuntu`, from `~/ai-fabric`
  unless a step says otherwise. Check the prompt before typing: it should read
  `ubuntu@oob-mgmt-server`.
- Type or paste **one line at a time**. The DSX Air web console scrambles
  multi-line pastes.

## 1. Create the simulation

**Recommended: import the saved topology.** In DSX Air, create a new
simulation from a file and choose [`topology/ai-fabric-dsx-air.json`](../topology/ai-fabric-dsx-air.json).
It contains all 13 devices, the 40 data links and the out-of-band management
network, with every cable matching the inventory.

**Or build it by hand** with these devices and cables:

| Devices | Image |
|---|---|
| Spine1-Spine4, Leaf1-Leaf5 | Cumulus VX 5.18.3 |
| Server1-Server4 | Ubuntu 24.04 |

| From | Ports | To |
|---|---|---|
| Leaf1-Leaf5 | swp1-swp4 | Spine1-Spine4 (Leaf N swp M goes to Spine M swp N) |
| Leaf1-Leaf5 | swp32, swp31, swp30, swp29 | Server1, Server2, Server3, Server4 |
| Server1-Server4 | eth1-eth5 | Leaf1-Leaf5 (one port per leaf: eth N goes to Leaf N) |

Leave every device's **eth0 unconnected** and turn on **Enable OOB**. DSX Air
then adds `oob-mgmt-server` and `oob-mgmt-switch` and wires every eth0 to them.
If any eth0 is cabled to another device, the toggle silently refuses to turn on.

Check before starting: the canvas shows `oob-mgmt-server` and
`oob-mgmt-switch` at the top. Then start the simulation. A started simulation
can't be edited, so get the cabling right first.

Management addresses handed out by DSX Air (useful when a name doesn't resolve):

| Device | eth0 | Device | eth0 |
|---|---|---|---|
| Leaf1 | 192.168.200.2 | Server1 | 192.168.200.7 |
| Leaf2 | 192.168.200.3 | Server2 | 192.168.200.8 |
| Leaf3 | 192.168.200.4 | Server3 | 192.168.200.9 |
| Leaf4 | 192.168.200.5 | Server4 | 192.168.200.10 |
| Leaf5 | 192.168.200.6 | Spine1 | 192.168.200.11 |
| | | Spine2 | 192.168.200.12 |
| | | Spine3 | 192.168.200.13 |
| | | Spine4 | 192.168.200.14 |

## 2. Prepare the management server

Open the console of `oob-mgmt-server` in DSX Air and log in as `ubuntu`.

```
sudo apt update
sudo apt install -y ansible git
ansible --version
ping -c 2 leaf1
```

Expected: `ansible --version` prints a version (2.10 or later), and `leaf1`
answers the ping. The management network's DNS resolves every device name.

## 3. First login and SSH keys (the only manual configuration)

Create a key for the management server. Press Enter at each question:

```
ssh-keygen -t ed25519
```

Log in to each device once with the default password DSX Air lists for its
image. The Cumulus switches then make you choose a new password. Do this for
every switch (user `cumulus`) and every server (user `ubuntu`):

```
ssh cumulus@spine1
exit
```

Repeat for `spine2` to `spine4`, `leaf1` to `leaf5`, and `ubuntu@server1` to
`ubuntu@server4`. Then copy the key to all of them, one line at a time:

```
for h in spine1 spine2 spine3 spine4 leaf1 leaf2 leaf3 leaf4 leaf5; do ssh-copy-id cumulus@$h; done
for h in server1 server2 server3 server4; do ssh-copy-id ubuntu@$h; done
```

Check: `ssh cumulus@leaf1 hostname` prints a name **without** asking for a
password.

## 4. Clone this repository

Give the management server access to GitHub. Print its public key:

```
cat ~/.ssh/id_ed25519.pub
```

Copy the whole line into GitHub: **Settings**, **SSH and GPG keys**,
**New SSH key**. Then, on the management server:

```
ssh -T git@github.com
git config --global user.name "Brett"
git config --global user.email "<your GitHub no-reply address>"
git clone git@github.com:sunnymajesticbay-ops/ai-fabric.git ~/ai-fabric
cd ~/ai-fabric
```

`ssh -T` should answer `Hi sunnymajesticbay-ops! You've successfully
authenticated`. Your no-reply address is under GitHub **Settings**, **Emails**;
using it keeps your personal email out of the commit history.

## 5. Check that Ansible reaches every device

```
ansible all -m ping
ansible servers -b -m command -a whoami
```

Expected: 13 green `SUCCESS` results with `"ping": "pong"`, then `root` from
each of the 4 servers (that confirms Ansible can use sudo on them, which step 7
needs). If the second command asks for a password or fails with
`Missing sudo password`, add `-K` to the two server playbooks in step 7.

## 6. Configure and verify the switches

```
ansible-playbook playbooks/underlay.yml
```

For each switch this writes the exact NVUE commands to `configs/<Switch>.sh`
(kept in Git), copies the file over and runs it. It sets the hostname,
loopback, BGP unnumbered on every fabric port, BFD (300 ms x 3), RoCE lossless
mode, and on leaves the server-facing addresses.

Expected `PLAY RECAP`: all 9 switches with `ok=3 changed=3 unreachable=0 failed=0`.

```
ansible-playbook playbooks/verify.yml
ansible-playbook playbooks/verify-roce.yml
```

Expected, per switch (the playbook waits up to a minute for sessions to come up):

| Switch | Message |
|---|---|
| Spine1-Spine4 | `5 of 5 BGP sessions established, 5 of 5 BFD sessions up` |
| Leaf1-Leaf5 | `4 of 4 BGP sessions established, 4 of 4 BFD sessions up` |
| All 9 | `RoCE lossless is configured` |

## 7. Configure and verify the servers

```
ansible-playbook playbooks/servers.yml
ansible-playbook playbooks/verify-servers.yml
```

`servers.yml` gives each server one address per rail (`10.<rail>.<server>.2/30`
on eth1-eth5) with source-based routing, so traffic leaves on the rail it was
sent from. `verify-servers.yml` pings 10 paths from each server.

Expected for each of the 4 servers:

```
10 of 10 paths OK
same rail, switch hops:  1 1 1 1 1
cross rail, switch hops:  3 3 3 3 3
```

One hop means the traffic stayed on its leaf; three means leaf, spine, leaf.

## 8. Save the result to GitHub

```
scripts/demo.sh sync "Rebuild of the fabric"
```

Expected: `PASS committed` (or `nothing new to commit` if the generated configs
are unchanged) and `PASS pushed`. The sync refuses to commit anything that
looks like an API key.

## 9. Optional: set up AI troubleshooting

The fabric doctor sends a snapshot of the switches to Claude for diagnosis. It
needs an Anthropic API key from platform.claude.com (**API keys**, **Create
key**; copy it with the Copy button, it is shown only once). Start the first line
with a space so the key stays out of your command history:

```
 export ANTHROPIC_API_KEY=<paste the key>
scripts/demo.sh savekey
scripts/demo.sh check
```

`check` should end with `All checks passed.` See [demo-runbook.md](demo-runbook.md)
for the rest.

## Build complete when

- [ ] `ansible all -m ping` returns 13 pongs
- [ ] `verify.yml`: 20 of 20 BGP sessions and 20 of 20 BFD sessions
- [ ] `verify-roce.yml`: RoCE lossless on all 9 switches
- [ ] `verify-servers.yml`: 40 of 40 paths (10 per server)
- [ ] `git status` shows nothing to commit and GitHub has the latest commit

## Changing the design later

Edit the variables, re-run the playbook, verify, sync:

| To change | Edit | Then run |
|---|---|---|
| BFD timers | `bfd_interval_ms`, `bfd_multiplier` in `inventory/group_vars/all.yml` | `underlay.yml`, `verify.yml` |
| RoCE on or off | `roce_enabled` in `inventory/group_vars/all.yml` | `underlay.yml`, `verify-roce.yml` |
| A switch's loopback or AS | `inventory/host_vars/<Switch>.yml` | `underlay.yml`, `verify.yml` |

`underlay.yml` only **sets** configuration. It never removes settings that are
no longer in the template, and it doesn't change whether a port is
administratively up or down. To bring shut ports back up, use
`scripts/demo.sh restore <Switch>`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Could not resolve hostname leaf1`, no DHCP leases, switch eth0 shows `NO-CARRIER` | The simulation has no out-of-band network | Rebuild from step 1 with every eth0 unconnected and **Enable OOB** on |
| The **Enable OOB** toggle won't turn on ("Automatic OOB network creation disabled") | Some device's eth0 is cabled to another device | Remove those links (servers use eth1-eth5 for data) or import the saved JSON |
| `ansible: command not found` | You are logged in to a switch, not the management server | `exit` until the prompt reads `ubuntu@oob-mgmt-server` |
| `Permission denied (publickey,password)` from Ansible | The key wasn't copied to that device | Run `ssh-copy-id` for that device again |
| `No route to host` after the simulation slept | Stale ARP entries on the management server | `sudo ip neigh flush all`, then retry |
| `^[[200~` appears and commands fail | The console's bracketed-paste mode | Type `printf '\e[?2004l'` by hand, then paste one line at a time |
| `fatal: not a git repository` | You are not in the repository folder | `cd ~/ai-fabric` |
| `Repository not found` on `git push` or `git clone` | Wrong repository name, or the server's key isn't on GitHub | `git remote -v` to check the address; redo step 4's key |
| BGP up but `0 of N BFD sessions up` | BFD is only configured on some switches | Re-run `underlay.yml` for all switches; BFD needs both ends |
| `FAILED: 10.x.y.2 -> 10.a.b.2` in `verify-servers.yml` | A server or leaf port isn't addressed | Re-run `underlay.yml`, then `servers.yml` |
