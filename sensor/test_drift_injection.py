#!/usr/bin/env python3
"""Exercise live feature-drift detection through the backend ingest route.

This sends synthetic 52-slot vectors, not network packets or verified attacks.
It sends no labels, so the adaptation trainer cannot treat these examples as
trusted training data.
"""

import argparse
import getpass
import random
import sys
import time
import uuid
from typing import Any

import requests

FEATURE_SCHEMA = "labrooms-app-layer-v2"
REFERENCE_SIZE = 500
POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 120


def make_flows(profile: str, count: int) -> list[dict[str, Any]]:
    rng = random.Random(42 if profile == "baseline" else 84)
    run_id = uuid.uuid4().hex[:10]
    flows = []

    for index in range(count):
        features = [0.0] * 52
        if profile == "baseline":
            duration_us = float(rng.randint(100_000, 200_000))
            fwd_bytes = float(rng.randint(800, 1_500))
            bwd_bytes = float(rng.randint(3_000, 7_000))
        else:
            # A sustained, short-duration burst with much larger forward
            # payloads shifts several monitored flow-feature distributions.
            duration_us = float(rng.randint(1_000, 5_000))
            fwd_bytes = float(rng.randint(50_000, 100_000))
            bwd_bytes = float(rng.randint(100, 500))

        features[0] = float(index + 1)
        features[1] = duration_us
        features[2] = 1.0
        features[3] = 1.0
        features[4] = fwd_bytes
        features[5] = bwd_bytes
        features[6] = fwd_bytes
        features[7] = fwd_bytes
        features[14] = (fwd_bytes + bwd_bytes) / (duration_us / 1_000_000)
        features[44] = 200.0

        flows.append({
            "flow_id": f"drift-test-{run_id}-{profile}-{index:04d}",
            "feature_schema": FEATURE_SCHEMA,
            "features": features,
        })

    return flows


def get_drift_status(session: requests.Session, ml_url: str) -> dict[str, Any]:
    response = session.get(f"{ml_url}/concept-drift", timeout=10)
    response.raise_for_status()
    return response.json()


def wait_for_samples(
    session: requests.Session,
    ml_url: str,
    target_samples: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    status = get_drift_status(session, ml_url)

    while status["samples_processed"] < target_samples:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"ML API processed {status['samples_processed']} samples; "
                f"expected at least {target_samples}. Check backend and ML API logs."
            )
        time.sleep(POLL_INTERVAL_SECONDS)
        status = get_drift_status(session, ml_url)

    return status


def send_batch(
    session: requests.Session,
    backend_url: str,
    sensor_key: str,
    profile: str,
) -> None:
    flows = make_flows(profile, REFERENCE_SIZE)
    response = session.post(
        backend_url,
        headers={"X-Sensor-Key": sensor_key},
        json={
            "sensor_id": f"drift-test-{profile}",
            "batch_timestamp": time.time(),
            "flow_count": len(flows),
            "flows": flows,
        },
        timeout=30,
    )
    if response.status_code != 202:
        raise RuntimeError(
            f"Backend rejected the {profile} batch "
            f"(HTTP {response.status_code}): {response.text[:500]}"
        )

    accepted = response.json().get("accepted", 0)
    if accepted != REFERENCE_SIZE:
        raise RuntimeError(
            f"Backend accepted {accepted} of {REFERENCE_SIZE} {profile} flows."
        )
    print(f"Backend accepted {accepted} unlabeled {profile} feature vectors.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test PSI drift detection with synthetic features through the backend."
    )
    parser.add_argument(
        "--backend-url",
        default="http://127.0.0.1:5000/api/telemetry/ingest",
        help="Backend telemetry ingest URL",
    )
    parser.add_argument(
        "--ml-url",
        default="http://127.0.0.1:5001",
        help="ML API base URL",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset demo drift/adaptation state before the run; requires DEMO_MODE=1",
    )
    args = parser.parse_args()

    sensor_key = getpass.getpass("Sensor API key (ca_live_...): ").strip()
    if not sensor_key.startswith("ca_live_"):
        print("A sensor key starting with ca_live_ is required.", file=sys.stderr)
        return 2

    session = requests.Session()
    try:
        if args.reset:
            response = session.post(f"{args.ml_url}/admin/reset", timeout=30)
            if response.status_code != 200:
                raise RuntimeError(
                    f"ML demo reset failed (HTTP {response.status_code}): "
                    f"{response.text[:500]}"
                )
            print("Reset ML drift/adaptation demo state.")

        initial = get_drift_status(session, args.ml_url)
        if initial["samples_processed"] != 0 or initial["drift_events"]:
            raise RuntimeError(
                "A clean drift baseline is required. Re-run with --reset "
                "(this clears the ML demo drift, adaptation, and evaluation state)."
            )

        print(
            f"Sending {REFERENCE_SIZE} baseline examples. "
            "Wait for these to reach inference before sending the shifted profile."
        )
        send_batch(session, args.backend_url, sensor_key, "baseline")
        baseline = wait_for_samples(
            session,
            args.ml_url,
            initial["samples_processed"] + REFERENCE_SIZE,
        )
        print(
            f"Baseline processed: {baseline['samples_processed']} samples; "
            f"state={baseline['drift_state']}."
        )

        print(
            f"Sending {REFERENCE_SIZE} shifted, short-duration burst examples "
            "to exercise the feature-distribution drift detector."
        )
        send_batch(session, args.backend_url, sensor_key, "shifted")
        final = wait_for_samples(
            session,
            args.ml_url,
            baseline["samples_processed"] + REFERENCE_SIZE,
        )

        psi = ", ".join(
            f"slot {feature['slot']} ({feature['name']}): {feature['drift']}"
            for feature in final["labrooms_features_drift"]
        )
        print(
            f"Final state={final['drift_state']}; "
            f"drift_detected={final['drift_detected']}; "
            f"processed={final['samples_processed']}."
        )
        print(f"Current PSI values (reference may rotate after an event): {psi}")
        if final["drift_events"]:
            event = final["drift_events"][0]
            print(
                f"Latest event: detector={event['detector']}, "
                f"signal={event['signal']}, detail={event['detail']}"
            )

        if not final["drift_detected"]:
            print(
                "No drift event fired. Check that the baseline and shifted "
                "batches reached the ML API and that no other traffic changed "
                "the baseline during this test.",
                file=sys.stderr,
            )
            return 1

        print(
            "Drift detection test passed. This demonstrates feature-distribution "
            "drift, not proof of a real attack or model accuracy."
        )
        return 0
    except (requests.RequestException, RuntimeError, TimeoutError, KeyError) as exc:
        print(f"Drift test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
