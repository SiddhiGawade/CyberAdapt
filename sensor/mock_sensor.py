#!/usr/bin/env python3
"""
CyberAdapt Mock Sensor — Generates fake network flow telemetry
for local testing WITHOUT needing Scapy, libpcap, or root access.

Usage:
  python mock_sensor.py --key "ca_live_..." --url "http://localhost:5000/api/telemetry/ingest"

Or via environment variables:
  SENSOR_KEY="ca_live_..."  INGEST_URL="http://localhost:5000/api/telemetry/ingest"  python mock_sensor.py
"""

import os
import sys
import time
import random
import string
import json
import argparse
import uuid

import requests

# ─────────────────── Fake Data Generators ────────────────────────

SAMPLE_IPS = [
    "192.168.1.10", "192.168.1.25", "10.0.0.5", "10.0.0.88",
    "172.16.0.12", "172.16.0.44", "203.0.113.50", "198.51.100.7",
    "192.168.2.100", "10.10.10.1", "8.8.8.8", "1.1.1.1",
    "93.184.216.34", "151.101.1.69", "104.16.132.229",
]

COMMON_PORTS = [80, 443, 53, 22, 8080, 3306, 5432, 6379, 25, 110, 993, 8443]
PROTOCOLS = [6, 17]  # TCP=6, UDP=17


def random_ip():
    return random.choice(SAMPLE_IPS)


def random_port():
    return random.choice(COMMON_PORTS) if random.random() < 0.7 else random.randint(1024, 65535)


def generate_flow():
    """Generate a single fake flow with realistic-looking 52 features."""
    src_ip = random_ip()
    dst_ip = random_ip()
    while dst_ip == src_ip:
        dst_ip = random_ip()

    src_port = random_port()
    dst_port = random_port()
    proto = random.choice(PROTOCOLS)

    flow_id = f"{src_ip}:{src_port}-{dst_ip}:{dst_port}-{proto}"

    # Generate plausible feature values
    duration_us = random.uniform(100, 30_000_000)       # 100µs to 30s
    fwd_pkts = random.randint(1, 500)
    bwd_pkts = random.randint(0, 300)
    total_pkts = fwd_pkts + bwd_pkts

    fwd_pkt_lens = [random.randint(40, 1500) for _ in range(fwd_pkts)]
    bwd_pkt_lens = [random.randint(40, 1500) for _ in range(bwd_pkts)] if bwd_pkts > 0 else []
    all_lens = fwd_pkt_lens + bwd_pkt_lens

    total_fwd_bytes = sum(fwd_pkt_lens)
    total_bwd_bytes = sum(bwd_pkt_lens)
    total_bytes = total_fwd_bytes + total_bwd_bytes
    duration_s = duration_us / 1e6 if duration_us > 0 else 1e-9

    def _mean(arr):
        return sum(arr) / len(arr) if arr else 0.0

    def _std(arr):
        if len(arr) < 2:
            return 0.0
        m = _mean(arr)
        return (sum((x - m) ** 2 for x in arr) / len(arr)) ** 0.5

    # IAT values (inter-arrival times in µs)
    flow_iats = sorted([random.uniform(10, duration_us / max(total_pkts, 1)) for _ in range(max(total_pkts - 1, 1))])
    fwd_iats = flow_iats[:max(fwd_pkts - 1, 1)]
    bwd_iats = flow_iats[:max(bwd_pkts - 1, 1)] if bwd_pkts > 1 else [0.0]

    # TCP flag counts (realistic)
    syn_count = random.randint(1, 3)
    ack_count = random.randint(fwd_pkts // 2, fwd_pkts + bwd_pkts)
    fin_count = random.choice([0, 0, 1, 2])
    rst_count = random.choice([0, 0, 0, 1])
    psh_count = random.randint(0, max(total_pkts // 3, 1))
    urg_count = random.choice([0, 0, 0, 0, 0, 1])

    features = [
        float(hash(flow_id) & 0xFFFFFFFF),               # 0:  Flow ID hash
        duration_us,                                       # 1:  Flow Duration (µs)
        float(fwd_pkts),                                   # 2:  Total Fwd Packets
        float(bwd_pkts),                                   # 3:  Total Bwd Packets
        float(total_fwd_bytes),                            # 4:  Total Fwd Bytes
        float(total_bwd_bytes),                            # 5:  Total Bwd Bytes
        float(max(fwd_pkt_lens)),                          # 6:  Fwd Pkt Len Max
        float(min(fwd_pkt_lens)),                          # 7:  Fwd Pkt Len Min
        _mean(fwd_pkt_lens),                               # 8:  Fwd Pkt Len Mean
        _std(fwd_pkt_lens),                                # 9:  Fwd Pkt Len Std
        float(max(bwd_pkt_lens) if bwd_pkt_lens else 0),  # 10: Bwd Pkt Len Max
        float(min(bwd_pkt_lens) if bwd_pkt_lens else 0),  # 11: Bwd Pkt Len Min
        _mean(bwd_pkt_lens),                               # 12: Bwd Pkt Len Mean
        _std(bwd_pkt_lens),                                # 13: Bwd Pkt Len Std
        total_bytes / duration_s,                          # 14: Flow Bytes/s
        total_pkts / duration_s,                           # 15: Flow Packets/s
        _mean(flow_iats),                                  # 16: Flow IAT Mean
        _std(flow_iats),                                   # 17: Flow IAT Std
        float(max(flow_iats)),                             # 18: Flow IAT Max
        float(min(flow_iats)),                             # 19: Flow IAT Min
        sum(fwd_iats),                                     # 20: Fwd IAT Total
        _mean(fwd_iats),                                   # 21: Fwd IAT Mean
        _std(fwd_iats),                                    # 22: Fwd IAT Std
        float(max(fwd_iats)),                              # 23: Fwd IAT Max
        float(min(fwd_iats)),                              # 24: Fwd IAT Min
        sum(bwd_iats),                                     # 25: Bwd IAT Total
        _mean(bwd_iats),                                   # 26: Bwd IAT Mean
        _std(bwd_iats),                                    # 27: Bwd IAT Std
        float(max(bwd_iats)),                              # 28: Bwd IAT Max
        float(min(bwd_iats)),                              # 29: Bwd IAT Min
        float(random.randint(0, psh_count)),               # 30: Fwd PSH Flags
        float(random.randint(0, max(psh_count // 2, 1))),  # 31: Bwd PSH Flags
        float(random.choice([0, 0, 0, 0, 1])),            # 32: Fwd URG Flags
        0.0,                                               # 33: Bwd URG Flags
        float(fwd_pkts * random.choice([20, 32, 40])),     # 34: Fwd Header Length
        float(bwd_pkts * random.choice([20, 32, 40])),     # 35: Bwd Header Length
        fwd_pkts / duration_s,                             # 36: Fwd Packets/s
        bwd_pkts / duration_s,                             # 37: Bwd Packets/s
        float(min(all_lens)) if all_lens else 0.0,         # 38: Min Pkt Length
        float(max(all_lens)) if all_lens else 0.0,         # 39: Max Pkt Length
        _mean(all_lens),                                   # 40: Pkt Len Mean
        _std(all_lens),                                    # 41: Pkt Len Std
        _std(all_lens) ** 2,                               # 42: Pkt Len Variance
        float(fin_count),                                  # 43: FIN Count
        float(syn_count),                                  # 44: SYN Count
        float(rst_count),                                  # 45: RST Count
        float(psh_count),                                  # 46: PSH Count
        float(ack_count),                                  # 47: ACK Count
        float(urg_count),                                  # 48: URG Count
        (bwd_pkts / fwd_pkts) if fwd_pkts else 0.0,       # 49: Down/Up Ratio
        total_bytes / total_pkts if total_pkts else 0.0,   # 50: Avg Pkt Size
        total_fwd_bytes / fwd_pkts if fwd_pkts else 0.0,  # 51: Fwd Avg Segment Size
    ]

    return {"flow_id": flow_id, "features": features}


# ─────────────────── Main Loop ───────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CyberAdapt Mock Sensor")
    parser.add_argument("--key", default=os.environ.get("SENSOR_KEY", ""), help="Sensor API key")
    parser.add_argument("--url", default=os.environ.get("INGEST_URL", "http://localhost:5000/api/telemetry/ingest"), help="Ingest URL")
    parser.add_argument("--interval", type=float, default=float(os.environ.get("BATCH_INTERVAL", "3")), help="Seconds between batches")
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "5")), help="Flows per batch")
    args = parser.parse_args()

    if not args.key:
        print("ERROR: --key or SENSOR_KEY env var is required")
        print("Run: node scripts/seed-dev.js  (in server/) to generate one")
        sys.exit(1)

    sensor_id = f"mock-{uuid.uuid4().hex[:8]}"
    session = requests.Session()
    session.headers.update({
        "X-Sensor-Key": args.key,
        "Content-Type": "application/json",
    })

    print("=" * 56)
    print("  CyberAdapt Mock Sensor")
    print(f"  Sensor ID  : {sensor_id}")
    print(f"  Ingest URL : {args.url}")
    print(f"  Batch Size : {args.batch_size} flows / {args.interval}s")
    print("=" * 56)
    print()

    batch_num = 0
    while True:
        batch_num += 1
        flows = [generate_flow() for _ in range(args.batch_size)]

        payload = {
            "sensor_id": sensor_id,
            "batch_timestamp": time.time(),
            "flow_count": len(flows),
            "flows": flows,
        }

        try:
            resp = session.post(args.url, json=payload, timeout=10)
            if resp.status_code in (200, 202):
                data = resp.json()
                print(f"[Batch {batch_num:04d}] OK  Sent {len(flows)} flows -> HTTP {resp.status_code}  (accepted: {data.get('accepted', '?')})")
            else:
                print(f"[Batch {batch_num:04d}] WARN  HTTP {resp.status_code}: {resp.text[:120]}")
        except requests.RequestException as e:
            print(f"[Batch {batch_num:04d}] ERR  Connection error: {e}")

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
