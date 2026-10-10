#!/usr/bin/env python3
"""
Direct feature fallback pipeline for CyberAdapt.

This script bypasses live HTTP traffic generation and sends valid 52-slot feature
vectors directly into the project’s model pipeline. It is intended as a backup
when a real attack generator or packet-capture environment is unavailable.

Usage examples:
  python sensor/direct_feature_injector.py --scenario dos --count 4 --mode backend
  python sensor/direct_feature_injector.py --scenario mixed --count 10 --mode ml
"""

import argparse
import os
import sys
import time
from typing import Dict, List

import requests

DEFAULT_KEY = os.environ.get(
    "CYBERADAPT_KEY",
    "ca_live_dc398aab2c79119b596f98a226cc38b6f31015d581205bc18210df2ac31e9e86",
)
DEFAULT_BACKEND_URL = os.environ.get(
    "FEATURE_FALLBACK_URL",
    "http://localhost:5000/api/telemetry/ingest",
)
DEFAULT_ML_URL = os.environ.get("ML_API_URL", "http://127.0.0.1:5001/predict")
FEATURE_SCHEMA = "labrooms-app-layer-v2"


def build_labrooms_flow(flow_id: str, duration_us: float, fwd_bytes: float, bwd_bytes: float, status_code: float) -> List[float]:
    """Build a valid 52-slot feature vector accepted by the ML API."""
    bytes_per_sec = (fwd_bytes + bwd_bytes) / (duration_us / 1e6) if duration_us > 0 else 0.0
    features = [0.0] * 52
    features[0] = float(hash(flow_id) & 0xFFFFFFFF)
    features[1] = float(duration_us)
    features[2] = 1.0
    features[3] = 1.0
    features[4] = float(fwd_bytes)
    features[5] = float(bwd_bytes)
    features[6] = float(fwd_bytes)
    features[7] = float(fwd_bytes)
    features[14] = float(bytes_per_sec)
    features[44] = float(status_code)
    return features


def attack_templates():
    return {
        "normal": {
            "flow_id": "NORMAL_DIRECT_01",
            "duration_us": 180_000.0,
            "fwd_bytes": 450.0,
            "bwd_bytes": 4_200.0,
            "status_code": 200.0,
            "label": "Normal Traffic",
        },
        "dos": {
            "flow_id": "DOS_DIRECT_01",
            "duration_us": 45_000_000.0,
            "fwd_bytes": 150.0,
            "bwd_bytes": 50.0,
            "status_code": 504.0,
            "label": "DoS",
        },
        "bruteforce": {
            "flow_id": "BRUTE_FORCE_DIRECT_01",
            "duration_us": 5_000.0,
            "fwd_bytes": 2_500.0,
            "bwd_bytes": 350.0,
            "status_code": 401.0,
            "label": "Brute Force",
        },
        "web": {
            "flow_id": "WEB_ATTACK_DIRECT_01",
            "duration_us": 250_000.0,
            "fwd_bytes": 18_500.0,
            "bwd_bytes": 1_200.0,
            "status_code": 500.0,
            "label": "Web Attacks",
        },
        "exfil": {
            "flow_id": "EXFIL_DIRECT_01",
            "duration_us": 1_200_000.0,
            "fwd_bytes": 850.0,
            "bwd_bytes": 120_500_000.0,
            "status_code": 200.0,
            "label": "Web Attacks",
        },
    }


def make_flow(template: Dict[str, float], index: int):
    flow_id = f"{template['flow_id']}_{index:02d}"
    features = build_labrooms_flow(
        flow_id=flow_id,
        duration_us=float(template["duration_us"]),
        fwd_bytes=float(template["fwd_bytes"]),
        bwd_bytes=float(template["bwd_bytes"]),
        status_code=float(template["status_code"]),
    )
    flow = {
        "flow_id": flow_id,
        "features": features,
        "feature_schema": FEATURE_SCHEMA,
        "ground_truth_label": template.get("label"),
    }
    return flow


def make_scenario(scenario: str, count: int):
    templates = attack_templates()
    if scenario == "mixed":
        cases = ["normal", "dos", "bruteforce", "web", "normal"]
    elif scenario in templates:
        cases = [scenario] * max(1, count)
    else:
        raise ValueError(f"Unsupported scenario: {scenario}")

    flows = []
    for i in range(count):
        kind = cases[i % len(cases)]
        flows.append(make_flow(templates[kind], i + 1))
    return flows


def post_to_backend(flows: List[dict], url: str, key: str):
    payload = {
        "sensor_id": "feature-fallback-sensor",
        "batch_timestamp": int(time.time() * 1000),
        "flow_count": len(flows),
        "flows": flows,
    }
    headers = {"X-Sensor-Key": key, "Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers, timeout=10)
    return response


def post_to_ml(flows: List[dict], url: str):
    response = requests.post(url, json={"flows": flows}, timeout=10)
    return response


def main():
    parser = argparse.ArgumentParser(description="Send valid feature vectors directly into the CyberAdapt model path")
    parser.add_argument("--scenario", choices=["normal", "dos", "bruteforce", "web", "exfil", "mixed"], default="mixed")
    parser.add_argument("--count", type=int, default=5, help="Number of direct feature flows to submit")
    parser.add_argument("--key", default=DEFAULT_KEY, help="Sensor key used when posting to the backend ingest route")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL, help="Backend feature fallback endpoint")
    parser.add_argument("--ml-url", default=DEFAULT_ML_URL, help="Direct ML model endpoint")
    parser.add_argument("--mode", choices=["backend", "ml"], default="backend", help="Use the backend feature route or call the ML API directly")
    args = parser.parse_args()

    if args.count <= 0:
        print("--count must be greater than 0")
        return 2

    flows = make_scenario(args.scenario, args.count)
    print(f"Sending {len(flows)} feature vectors with scenario={args.scenario} via {args.mode}")

    try:
        if args.mode == "backend":
            resp = post_to_backend(flows, args.backend_url, args.key)
            print(f"Backend response: HTTP {resp.status_code}")
            print(resp.text)
        else:
            resp = post_to_ml(flows, args.ml_url)
            print(f"ML API response: HTTP {resp.status_code}")
            try:
                print(resp.json())
            except ValueError:
                print(resp.text)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety path
        print(f"Direct feature injection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
