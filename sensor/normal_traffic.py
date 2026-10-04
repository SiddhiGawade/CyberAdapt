#!/usr/bin/env python3
"""
CyberAdapt Normal Traffic Generator — sustained benign flow telemetry.

Emulates ordinary users browsing the Labrooms site: short HTTP request /
response exchanges that the champion model should label "Normal Traffic"
with no rule-override firing. This is the demo's "before" state and the
adaptation buffer's high-confidence Normal label source.

Each flow is a 52-slot Labrooms vector with the same layout as
simulate_attacks.build_labrooms_flow (10 populated slots, rest zeroed):
  [1]  Flow Duration (µs)      — lognormal, clamped 5 ms … 900 ms
  [2]  Total Fwd Packets       — 1 (occasionally 2)
  [3]  Total Bwd Packets       — 1 (occasionally 2)
  [4]  Total Fwd Bytes         — request size   180 … 2,600 B
  [5]  Total Bwd Bytes         — response size  400 … 80,000 B
  [6]  Fwd Pkt Len Max         — same distribution as slot 4
  [7]  Fwd Pkt Len Min         — same distribution as slot 4
  [14] Flow Bytes/s            — derived: (fwd + bwd bytes) / duration_s
  [44] HTTP Status Code        — 200 (.93) / 304 (.03) / 404 (.03) / 301 (.01)

Rule-override safety (ml/api.py thresholds): duration stays << 30 s, bwd
bytes << 10 MB, no 401/403/500/504 statuses, and 404 bodies are kept small
+ rate-limited so Flow Bytes/s never exceeds the 100 kB/s Brute-Force trip
line for error statuses.

Usage:
  python sensor/normal_traffic.py --key "ca_live_..." [--duration 60]

Or via environment variables:
  SENSOR_KEY="ca_live_..."  INGEST_URL="http://localhost:5000/api/telemetry/ingest"  python sensor/normal_traffic.py
"""

import argparse
import os
import random
import sys
import time

import requests

SENSOR_ID = "normal-traffic-gen"
DEFAULT_INGEST_URL = "http://localhost:5000/api/telemetry/ingest"

# ─────────────────── Benign Traffic Profile ──────────────────────

CLIENT_IPS = [
    "192.168.1.10", "192.168.1.25", "192.168.1.63", "192.168.2.100",
    "10.0.0.5", "10.0.0.88", "172.16.0.12", "172.16.0.44",
    "203.0.113.50", "198.51.100.7",
]
LABROOMS_SERVERS = ["10.10.10.20", "10.10.10.21", "192.168.1.50"]
SERVER_PORTS = [443, 443, 443, 80]          # mostly HTTPS

STATUS_CODES = [200, 304, 404, 301]
STATUS_WEIGHTS = [0.93, 0.03, 0.03, 0.01]

DURATION_MIN_US = 5_000.0                   # 5 ms
DURATION_MAX_US = 900_000.0                 # 900 ms  (Slowloris rule: >30 s)

# api.py fires "Brute Force" on HTTP 404 when Flow Bytes/s > 100_000 —
# error-status flows stay under this safety ceiling (20% margin).
ERR_STATUS_MAX_BPS = 80_000.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def build_normal_flow(flow_id: str) -> list:
    """Build one benign 52-slot Labrooms feature vector."""
    status = random.choices(STATUS_CODES, weights=STATUS_WEIGHTS, k=1)[0]

    duration_us = _clamp(random.lognormvariate(12.0, 0.6), DURATION_MIN_US, DURATION_MAX_US)
    fwd_pkts = 1 if random.random() < 0.9 else 2
    bwd_pkts = 1 if random.random() < 0.9 else 2
    fwd_bytes = float(random.randint(180, 2600))
    # 404 responses are tiny error pages — small body keeps the derived
    # byte-rate far from the Brute-Force trip line for any duration.
    if status == 404:
        bwd_bytes = float(random.randint(150, 1500))
    else:
        bwd_bytes = float(random.randint(400, 80_000))

    bytes_per_sec = (fwd_bytes + bwd_bytes) / (duration_us / 1e6)
    if status == 404 and bytes_per_sec > ERR_STATUS_MAX_BPS:
        duration_us = _clamp(
            (fwd_bytes + bwd_bytes) / ERR_STATUS_MAX_BPS * 1e6,
            DURATION_MIN_US, DURATION_MAX_US,
        )
        bytes_per_sec = (fwd_bytes + bwd_bytes) / (duration_us / 1e6)

    features = [0.0] * 52
    features[0]  = float(hash(flow_id) & 0xFFFFFFFF)  # [0]  Flow ID Hash
    features[1]  = float(duration_us)                 # [1]  Flow Duration (µs)
    features[2]  = float(fwd_pkts)                    # [2]  Total Fwd Packets
    features[3]  = float(bwd_pkts)                    # [3]  Total Bwd Packets
    features[4]  = fwd_bytes                          # [4]  Total Fwd Bytes
    features[5]  = bwd_bytes                          # [5]  Total Bwd Bytes
    features[6]  = fwd_bytes                          # [6]  Fwd Pkt Len Max
    features[7]  = fwd_bytes                          # [7]  Fwd Pkt Len Min
    features[14] = float(bytes_per_sec)               # [14] Flow Bytes/s
    features[44] = float(status)                      # [44] HTTP Status Code
    return features


def make_flow_id(lbl_tag: bool) -> str:
    """Realistic web-flow id; optional LBL:: ground-truth prefix (§5.4)."""
    src = random.choice(CLIENT_IPS)
    dst = random.choice(LABROOMS_SERVERS)
    flow_id = f"{src}:{random.randint(49152, 65535)}->{dst}:{random.choice(SERVER_PORTS)}-6"
    return f"LBL::Normal_Traffic::{flow_id}" if lbl_tag else flow_id


# ─────────────────── Main Loop ───────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="CyberAdapt Normal Traffic Generator")
    parser.add_argument("--key", default=os.environ.get("SENSOR_KEY", ""), help="Sensor API key")
    parser.add_argument("--url", default=os.environ.get("INGEST_URL", DEFAULT_INGEST_URL), help="Ingest URL")
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between batches (default 2)")
    parser.add_argument("--batch-size", type=int, default=8, help="Flows per batch (default 8)")
    parser.add_argument("--duration", type=float, default=None, help="Total seconds to run (default: until Ctrl+C)")
    parser.add_argument("--jitter", type=float, default=0.25, help="plus/minus fraction applied to --interval (default 0.25, 0 disables)")
    parser.add_argument("--lbl-tag", action="store_true", help="Prefix flow_ids with LBL::Normal_Traffic::")
    args = parser.parse_args()

    if not args.key:
        print("ERROR: --key or SENSOR_KEY env var is required")
        print("Run: node scripts/seed-dev.js  (in server/) to generate one")
        return 1

    if args.interval <= 0:
        print("ERROR: --interval must be > 0")
        return 1
    jitter = _clamp(args.jitter, 0.0, 0.95)

    session = requests.Session()
    session.headers.update({
        "X-Sensor-Key": args.key,
        "Content-Type": "application/json",
    })

    print("=" * 56)
    print("  CyberAdapt Normal Traffic Generator")
    print(f"  Sensor ID  : {SENSOR_ID}")
    print(f"  Ingest URL : {args.url}")
    print(f"  Batch Size : {args.batch_size} flows / {args.interval}s +/-{jitter:.0%}")
    print(f"  Duration   : {'until Ctrl+C' if args.duration is None else f'{args.duration:g}s'}")
    print(f"  LBL tags   : {'ON (LBL::Normal_Traffic::)' if args.lbl_tag else 'off'}")
    print("=" * 56)
    print()

    batch_num = 0
    batches_ok = 0
    batches_err = 0
    flows_sent = 0
    started = time.monotonic()

    try:
        while True:
            if args.duration is not None and time.monotonic() - started >= args.duration:
                break

            batch_num += 1
            flows = []
            for _ in range(max(1, args.batch_size)):
                fid = make_flow_id(args.lbl_tag)
                flows.append({"flow_id": fid, "features": build_normal_flow(fid)})

            payload = {
                "sensor_id": SENSOR_ID,
                "batch_timestamp": int(time.time() * 1000),
                "flow_count": len(flows),
                "flows": flows,
            }

            try:
                resp = session.post(args.url, json=payload, timeout=10)
                if resp.status_code in (200, 202):
                    batches_ok += 1
                    flows_sent += len(flows)
                    accepted = resp.json().get("accepted", "?")
                    print(f"[Batch {batch_num:04d}] OK  Sent {len(flows)} flows -> HTTP {resp.status_code}  (accepted: {accepted})", flush=True)
                else:
                    batches_err += 1
                    print(f"[Batch {batch_num:04d}] WARN  HTTP {resp.status_code}: {resp.text[:120]}", flush=True)
            except requests.RequestException as e:
                batches_err += 1
                print(f"[Batch {batch_num:04d}] ERR  Connection error: {e}", flush=True)

            sleep_s = max(0.05, args.interval * (1.0 + random.uniform(-jitter, jitter)))
            if args.duration is not None:
                remaining = args.duration - (time.monotonic() - started)
                if remaining <= 0:
                    break
                sleep_s = min(sleep_s, remaining)
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl+C).")
    finally:
        elapsed = max(time.monotonic() - started, 1e-9)
        print()
        print("-" * 56)
        print("  Normal Traffic Generator - summary")
        print(f"  Elapsed        : {elapsed:.1f}s")
        print(f"  Batches OK/err : {batches_ok} / {batches_err}")
        print(f"  Flows accepted : {flows_sent}  ({flows_sent / elapsed:.1f} flows/s)")
        print("-" * 56)

    return 0


if __name__ == "__main__":
    sys.exit(main())
