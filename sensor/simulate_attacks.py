#!/usr/bin/env python3
"""
Attack Simulator for CyberAdapt Labrooms Sensor Pipeline
Generates targeted application-layer attack flows matching Labrooms 10-feature spec:
- DoS / Slowloris Attack (High Flow Duration [1])
- Data Exfiltration (Massive Bwd Bytes [5])
- Brute Force / Scraping (High Bytes/s [14], HTTP 401/404 Status Code [44])
- Web Attack / Server Error (5xx Status Code [44] with SQLi / XSS payload lengths)
"""

import sys
import time
import random
import requests
import argparse

INGEST_URL = "http://localhost:5000/api/telemetry/ingest"
DEFAULT_KEY = "ca_live_dc398aab2c79119b596f98a226cc38b6f31015d581205bc18210df2ac31e9e86"

def build_labrooms_flow(
    flow_id: str,
    duration_us: float,
    fwd_bytes: float,
    bwd_bytes: float,
    status_code: float
) -> list:
    """Build a 52-slot Labrooms feature vector according to the 10-feature contract."""
    bytes_per_sec = (fwd_bytes + bwd_bytes) / (duration_us / 1e6) if duration_us > 0 else 0.0

    # Initialize 52-feature array with zeros
    features = [0.0] * 52

    features[0]  = float(hash(flow_id) & 0xFFFFFFFF)  # [0] Flow ID Hash
    features[1]  = float(duration_us)                 # [1] Flow Duration (µs)
    features[2]  = 1.0                                # [2] Total Fwd Packets (HTTP Req)
    features[3]  = 1.0                                # [3] Total Bwd Packets (HTTP Res)
    features[4]  = float(fwd_bytes)                   # [4] Total Fwd Bytes (Req Size)
    features[5]  = float(bwd_bytes)                   # [5] Total Bwd Bytes (Res Size)
    features[6]  = float(fwd_bytes)                   # [6] Fwd Pkt Len Max
    features[7]  = float(fwd_bytes)                   # [7] Fwd Pkt Len Min
    features[14] = float(bytes_per_sec)               # [14] Flow Bytes/s
    features[44] = float(status_code)                 # [44] SYN Slot hijacked for HTTP Status Code

    return features

def generate_attack_scenario():
    """Generate a batch of 4 distinct attack flows + 1 normal flow."""
    flows = []

    # 1. DoS / Slowloris Attack (Extremely long duration, tiny byte count)
    dos_flow = build_labrooms_flow(
        flow_id="ATTACK_DOS_SLOWLORIS_01",
        duration_us=45_000_000.0,  # 45 seconds
        fwd_bytes=150.0,
        bwd_bytes=40.0,
        status_code=504.0           # Gateway Timeout
    )
    flows.append({"flow_id": "ATTACK_DOS_SLOWLORIS_01", "features": dos_flow})

    # 2. Data Exfiltration (Massive HTTP response byte transfer)
    exfil_flow = build_labrooms_flow(
        flow_id="ATTACK_DATA_EXFIL_02",
        duration_us=1_200_000.0,   # 1.2s
        fwd_bytes=850.0,
        bwd_bytes=120_500_000.0,   # 120 MB response payload
        status_code=200.0
    )
    flows.append({"flow_id": "ATTACK_DATA_EXFIL_02", "features": exfil_flow})

    # 3. Brute Force / Credential Stuffing (Extremely high rate & 401 Unauthorized)
    bf_flow = build_labrooms_flow(
        flow_id="ATTACK_BRUTE_FORCE_03",
        duration_us=5_000.0,       # 5 ms (burst)
        fwd_bytes=2_500.0,
        bwd_bytes=350.0,
        status_code=401.0           # Unauthorized
    )
    flows.append({"flow_id": "ATTACK_BRUTE_FORCE_03", "features": bf_flow})

    # 4. Web Attack (SQL Injection / Path Traversal -> 500 Internal Server Error)
    sqli_flow = build_labrooms_flow(
        flow_id="ATTACK_SQLI_WEB_04",
        duration_us=250_000.0,     # 250 ms
        fwd_bytes=18_500.0,        # Large SQLi payload in URL/body
        bwd_bytes=1_200.0,
        status_code=500.0           # Internal Server Error
    )
    flows.append({"flow_id": "ATTACK_SQLI_WEB_04", "features": sqli_flow})

    # 5. Normal Traffic (Standard web request)
    normal_flow = build_labrooms_flow(
        flow_id="NORMAL_WEB_REQ_05",
        duration_us=180_000.0,     # 180 ms
        fwd_bytes=450.0,
        bwd_bytes=4_200.0,
        status_code=200.0
    )
    flows.append({"flow_id": "NORMAL_WEB_REQ_05", "features": normal_flow})

    return flows

def main():
    parser = argparse.ArgumentParser(description="Simulate CyberAdapt Attacks")
    parser.add_argument("--key", default=DEFAULT_KEY, help="Sensor API Key")
    parser.add_argument("--url", default=INGEST_URL, help="Backend Ingest Endpoint")
    args = parser.parse_args()

    print("\n⚔️  CyberAdapt Attack Simulation Tool")
    print(f"   Target Ingest URL: {args.url}")
    print(f"   Sensor Key:       {args.key[:12]}...")

    flows = generate_attack_scenario()

    payload = {
        "sensor_id": "attack-sim-sensor-01",
        "batch_timestamp": int(time.time() * 1000),
        "flow_count": len(flows),
        "flows": flows
    }

    headers = {
        "X-Sensor-Key": args.key,
        "Content-Type": "application/json"
    }

    print(f"\n🚀 Sending batch of {len(flows)} simulated flows (4 attacks + 1 normal)...")
    try:
        res = requests.post(args.url, json=payload, headers=headers, timeout=5)
        print(f"   Ingestion Response: HTTP {res.status_code}")
        print(f"   Payload Response:   {res.text}")

        print("\n⏳ Waiting 2 seconds for asynchronous ML classification & database annotation...")
        time.sleep(2)

        # Query python ML API directly to verify real-time inference prediction output
        ml_predict_url = "http://127.0.0.1:5001/predict"
        ml_res = requests.post(ml_predict_url, json={"flows": flows}, timeout=5)

        if ml_res.status_code == 200:
            predictions = ml_res.json().get("predictions", [])
            print("\n🤖 Real-time ML Inference Model Predictions:")
            print("=" * 70)
            for p in predictions:
                print(f"  Flow ID    : {p['flow_id']}")
                print(f"  Threat     : {p['label']} (Index: {p['label_index']})")
                print(f"  Confidence : {(p['confidence'] * 100):.1f}%")
                print("-" * 70)
        else:
            print(f"   ML direct prediction query failed: HTTP {ml_res.status_code}")

    except Exception as e:
        print(f"❌ Simulation failed: {e}")

if __name__ == "__main__":
    main()
