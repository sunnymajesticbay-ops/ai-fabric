#!/usr/bin/env python3
"""summarize_results.py: turn a test run's CSV files into the numbers the test runbook checks.

Usage, from the repo folder on the OOB server (only Python's standard library is needed):

    python3 scripts/summarize_results.py results-bfd            # one run
    python3 scripts/summarize_results.py results results-bfd    # compare runs side by side

It recognizes each folder by the files the playbooks write:
  traffic.yml   -> counters.csv + events.csv   (phases, spine shares, the Spine2 failure)
  threshold.yml -> ports.csv + cpu.csv          (delivered traffic and CPU per load step)
  ceiling.yml   -> summary.csv                  (Mbit/s and retransmits for tests A to E)

Delivered traffic = bytes the leaves send to servers (leaf ports swp29-swp32), the same
measure used in the slides, resampled onto a 2-second grid.
"""
import csv
import os
import sys
from bisect import bisect_left
from collections import defaultdict

SERVER_PORTS = {"swp29", "swp30", "swp31", "swp32"}
STEP = 2.0


def interp(t, ts, vs):
    """Linear interpolation of a cumulative counter at time t (clamped at the ends)."""
    if t <= ts[0]:
        return vs[0]
    if t >= ts[-1]:
        return vs[-1]
    i = bisect_left(ts, t)
    t0, t1, v0, v1 = ts[i - 1], ts[i], vs[i - 1], vs[i]
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1


def load_series(path, node_col):
    """{(node, port): (times_s, rx_bytes, tx_bytes, drops)} sorted by time."""
    raw = defaultdict(list)
    with open(path) as f:
        for r in csv.DictReader(f):
            drops = int(r.get("rx_dropped") or 0) + int(r.get("tx_dropped") or 0)
            raw[(r[node_col], r["port"])].append((int(r["elapsed_ms"]) / 1000, int(r["rx_bytes"]), int(r["tx_bytes"]), drops))
    out = {}
    for k, rows in raw.items():
        rows.sort()
        out[k] = tuple(list(c) for c in zip(*rows))
    return out


def grid_rates(series, direction, keep):
    """Sum of Mbit/s over the selected ports, on a common 2 s grid. Returns (mid_times, values)."""
    sel = {k: v for k, v in series.items() if keep(k)}
    end = min(v[0][-1] for v in sel.values())
    n = int(end // STEP)
    grid = [i * STEP for i in range(n + 1)]
    total = [0.0] * n
    col = 1 if direction == "rx" else 2
    for ts, *cols in sel.values():
        vs = cols[col - 1]
        prev = interp(grid[0], ts, vs)
        for i in range(n):
            cur = interp(grid[i + 1], ts, vs)
            total[i] += max(0.0, cur - prev) * 8 / 1e6 / STEP
            prev = cur
    mids = [g + STEP / 2 for g in grid[:-1]]
    return mids, total


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def load_events(path):
    with open(path) as f:
        return [(int(r["elapsed_ms"]) / 1000, r["event"]) for r in csv.DictReader(f)]


# ---------------------------------------------------------------------------------------------
def traffic(folder):
    s = load_series(os.path.join(folder, "counters.csv"), "switch")
    ev = load_events(os.path.join(folder, "events.csv"))
    t, dl = grid_rates(s, "tx", lambda k: k[0].startswith("Leaf") and k[1] in SERVER_PORTS)
    bounds = ev + [(t[-1] + 1, "end")]
    phases = {}
    for (a, name), (b, _) in zip(bounds, bounds[1:]):
        if name in ("Same-rail traffic", "Cross-rail light"):
            phases[name] = mean(v for x, v in zip(t, dl) if a + 6 < x < b - 2)
    when = {name: a for a, name in ev}
    heavy, down, up = when.get("Cross-rail heavy"), when.get("Spine2 down"), when.get("Spine2 restored")
    out = {"Same-rail delivered (Mbit/s)": phases.get("Same-rail traffic"),
           "Cross-rail light delivered (Mbit/s)": phases.get("Cross-rail light")}
    if heavy is not None and down is not None:
        base = mean(v for x, v in zip(t, dl) if heavy + 6 < x < down - 2)
        out["Cross-rail heavy delivered (Mbit/s)"] = base
        # spine shares while all four spines were up
        shares = {}
        for sp in range(1, 5):
            _, v = grid_rates(s, "rx", lambda k, sp=sp: k[0].startswith("Leaf") and k[1] == f"swp{sp}")
            shares[sp] = mean(y for x, y in zip(t, v) if heavy + 6 < x < down - 2)
        tot = sum(shares.values())
        out["Spine shares, heavy phase (1/2/3/4)"] = "/".join(f"{100 * shares[i] / tot:.0f}%" for i in range(1, 5))
        win = [(x, v) for x, v in zip(t, dl) if down <= x <= down + 30]
        low = min(v for _, v in win)
        dip = sum(STEP for _, v in win if v < 0.9 * base)
        held = sum(max(0.0, base - v) * STEP for _, v in win)
        out["Spine2 failure: lowest delivered (Mbit/s)"] = low
        out["Spine2 failure: worst drop"] = f"{100 * (1 - low / base):.0f}%"
        out["Spine2 failure: time below 90% of normal (s)"] = dip
        out["Spine2 failure: traffic held back (Mbit)"] = held
        if up is not None:
            out["Spine2 down for (s)"] = up - down
    return out


def threshold(folder):
    s = load_series(os.path.join(folder, "ports.csv"), "node")
    ev = load_events(os.path.join(folder, "events.csv"))
    t, dl = grid_rates(s, "tx", lambda k: k[0].startswith("Leaf") and k[1] in SERVER_PORTS)
    cpu = defaultdict(list)
    with open(os.path.join(folder, "cpu.csv")) as f:
        for r in csv.DictReader(f):
            cpu[r["node"]].append((int(r["elapsed_ms"]) / 1000, int(r["cpu_total"]), int(r["cpu_idle"])))
    busy = {}
    for node, rows in cpu.items():
        rows.sort()
        busy[node] = [((a[0] + b[0]) / 2, 100 * (1 - (b[2] - a[2]) / max(b[1] - a[1], 1))) for a, b in zip(rows, rows[1:])]
    out = {}
    bounds = ev + [(t[-1] + 1, "end")]
    for (a, name), (b, _) in zip(bounds, bounds[1:]):
        if name == "Idle":
            continue
        rate = float(name.split("M")[0])
        d = mean(v for x, v in zip(t, dl) if a + 5 < x < b - 5) / 1000
        tier = {}
        for prefix in ("Leaf", "Spine", "Server"):
            vals = [mean(v for x, v in busy[n] if a + 5 < x < b - 5) for n in busy if n.startswith(prefix)]
            tier[prefix] = max(vals) if vals else float("nan")
        out[f"{name}: requested / delivered (Gbit/s)"] = f"{60 * rate / 1000:.2f} / {d:.2f}"
        out[f"{name}: busiest leaf / spine / server CPU"] = f"{tier['Leaf']:.0f}% / {tier['Spine']:.0f}% / {tier['Server']:.0f}%"
    drops = sum(v[3][-1] - v[3][0] for v in s.values())
    out["Packets dropped, all ports, whole run"] = drops
    return out


def ceiling(folder):
    out = {}
    with open(os.path.join(folder, "summary.csv")) as f:
        for r in csv.DictReader(f):
            name = r["test"].split()[0]
            out[f"{r['test']} (Mbit/s)"] = float(r["mbit_s"])
            if "retransmits" in r:
                out[f"{name} retransmits"] = int(r["retransmits"])
    return out


def summarize(folder):
    has = set(os.listdir(folder))
    if {"counters.csv", "events.csv"} <= has:
        return "traffic", traffic(folder)
    if {"ports.csv", "cpu.csv", "events.csv"} <= has:
        return "threshold", threshold(folder)
    if "summary.csv" in has:
        return "ceiling", ceiling(folder)
    sys.exit(f"{folder}: no counters.csv, ports.csv or summary.csv found")


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 10 else f"{v:.1f}"
    return str(v)


def main():
    folders = sys.argv[1:]
    if not folders:
        sys.exit(__doc__)
    results = [(f, *summarize(f)) for f in folders]
    kinds = {k for _, k, _ in results}
    if len(kinds) > 1:
        sys.exit("Compare folders from the same kind of test (traffic, threshold or ceiling).")
    keys = list(dict.fromkeys(k for _, _, d in results for k in d))
    w0 = max(len(k) for k in keys)
    ws = [max(len(os.path.basename(f.rstrip("/"))), *(len(fmt(d.get(k))) for k in keys)) for f, _, d in results]
    print(f"{kinds.pop()} test")
    print(" " * w0 + "  " + "  ".join(os.path.basename(f.rstrip("/")).rjust(w) for (f, _, _), w in zip(results, ws)))
    for k in keys:
        print(k.ljust(w0) + "  " + "  ".join(fmt(d.get(k)).rjust(w) for (_, _, d), w in zip(results, ws)))


if __name__ == "__main__":
    main()
