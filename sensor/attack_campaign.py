#!/usr/bin/env python3
"""
Attack Campaign Generator for CyberAdapt Labrooms Sensor Pipeline
=================================================================
Sustained, phased attack campaign — pushes ADWIN over the drift threshold
and fills the adaptation buffer with LBL::-tagged ground-truth samples.

Phases (--scenario mixed, default):
  1. warmup      30 s — normal-only trickle (baseline settles)
  2. dos         45 s — Slowloris: duration 30–90 s, tiny bytes, status 504
  3. bruteforce  45 s — 1–20 ms bursts, fwd 1–4 kB, status 401/403, high B/s
  4. sqli        45 s — fwd 8–25 kB payloads, status 500, moderate duration
  5. exfil       45 s — bwd 15–150 MB, status 200, duration ~1 s
  6. cooldown    30 s — back to normal trickle

Modes:
  --mode ingest  (default) emit attack-profile flows to /api/telemetry/ingest
  --mode live    additionally fire mild real HTTP requests at --target while
                 emitting matching flow vectors (audience effect only —
                 the emitted vectors are what the pipeline scores)

Every flow_id is ground-truth tagged  LBL::<CLASS>::<desc>-<rand>
(master plan §5.4) unless --no-lbl-tag is passed.

Usage:
  python sensor/attack_campaign.py --key "ca_live_..." --scenario mixed
  python sensor/attack_campaign.py --key "ca_live_..." --scenario dos --mode live --target http://localhost:3000
"""

import argparse
import os
import random
import socket
import sys
import threading
import time
import uuid
from urllib.parse import urlparse

import requests

# Windows consoles default to cp1252 — reconfigure so phase banners print.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

INGEST_URL = "http://localhost:5000/api/telemetry/ingest"

PHASE_SECONDS = {
    "warmup": 30, "dos": 45, "bruteforce": 45,
    "sqli": 45, "exfil": 45, "cooldown": 30,
}
SCENARIOS = {
    "mixed":      ["warmup", "dos", "bruteforce", "sqli", "exfil", "cooldown"],
    "dos":        ["warmup", "dos", "cooldown"],
    "bruteforce": ["warmup", "bruteforce", "cooldown"],
    "sqli":       ["warmup", "sqli", "cooldown"],
    "exfil":      ["warmup", "exfil", "cooldown"],
}
SQLI_STRINGS = ["' OR 1=1--", "' UNION SELECT null,version()--",
                "<script>alert(1)</script>", "../../etc/passwd", "1'; DROP TABLE users--"]


# ─────────────────── Flow Vector Builders ──────────────────────

def build_labrooms_flow(flow_id: str, duration_us: float,
                        fwd_bytes: float, bwd_bytes: float,
                        status_code: float) -> list:
    """Build a 52-slot Labrooms feature vector (same contract as simulate_attacks.py)."""
    bytes_per_sec = (fwd_bytes + bwd_bytes) / (duration_us / 1e6) if duration_us > 0 else 0.0
    features = [0.0] * 52
    features[0]  = float(hash(flow_id) & 0xFFFFFFFF)  # [0] Flow ID Hash
    features[1]  = float(duration_us)                 # [1] Flow Duration (µs)
    features[2]  = 1.0                                # [2] Total Fwd Packets
    features[3]  = 1.0                                # [3] Total Bwd Packets
    features[4]  = float(fwd_bytes)                   # [4] Total Fwd Bytes
    features[5]  = float(bwd_bytes)                   # [5] Total Bwd Bytes
    features[6]  = float(fwd_bytes)                   # [6] Fwd Pkt Len Max
    features[7]  = float(fwd_bytes)                   # [7] Fwd Pkt Len Min
    features[14] = float(bytes_per_sec)               # [14] Flow Bytes/s
    features[44] = float(status_code)                 # [44] SYN Slot → HTTP Status Code
    return features


def _flow(phase: str, cls: str, desc: str, duration_us: float,
          fwd: float, bwd: float, status: float, tag: bool) -> dict:
    """One flow dict. LBL::<CLASS>::<desc>-<rand> carries simulator ground truth."""
    fid = f"LBL::{cls}::{desc}-{uuid.uuid4().hex[:4]}" if tag else f"{phase}-{uuid.uuid4().hex[:8]}"
    return {"flow_id": fid,
            "features": build_labrooms_flow(fid, duration_us, fwd, bwd, status)}


# Per-phase randomized envelopes — parameters vary per flow so ADWIN sees a
# distribution, not a trivial step function.
def gen_normal(phase: str, tag: bool) -> dict:
    return _flow(phase, "Normal_Traffic", "web",
                 random.uniform(40_000, 480_000),           # 40–480 ms
                 random.uniform(200, 2_000),
                 random.uniform(800, 22_000),
                 random.choices([200.0, 301.0, 404.0], weights=[85, 5, 10])[0], tag)

def gen_dos(phase: str, tag: bool) -> dict:
    # Slowloris — always trips rule 1 (duration>30s OR 504) → "DoS"
    return _flow(phase, "DoS", "slowloris",
                 random.uniform(30_000_000, 90_000_000),    # 30–90 s
                 random.uniform(80, 400),
                 random.uniform(20, 150),
                 random.choices([504.0, 408.0, 200.0], weights=[80, 10, 10])[0], tag)

def gen_bruteforce(phase: str, tag: bool) -> dict:
    # 1–20 ms + 401/403 → "Brute Force"; bytes/s auto-computes >100 kB/s
    return _flow(phase, "Brute_Force", "login",
                 random.uniform(1_000, 20_000),
                 random.uniform(1_000, 4_000),
                 random.uniform(200, 900),
                 random.choices([401.0, 403.0], weights=[80, 20])[0], tag)

def gen_sqli(phase: str, tag: bool) -> dict:
    # large request payload + HTTP 500 → "Web Attacks"
    return _flow(phase, "Web_Attacks", "sqli",
                 random.uniform(80_000, 600_000),           # 80–600 ms
                 random.uniform(8_000, 25_000),
                 random.uniform(400, 3_000),
                 500.0, tag)

def gen_exfil(phase: str, tag: bool) -> dict:
    # bwd_bytes >10 MB → rule 2 → "Web Attacks" (no Exfiltration class exists)
    return _flow(phase, "Web_Attacks", "exfil",
                 random.uniform(600_000, 1_500_000),        # ~1 s
                 random.uniform(300, 1_200),
                 random.uniform(15_000_000, 150_000_000),   # 15–150 MB
                 200.0, tag)

GENERATORS = {"warmup": gen_normal, "cooldown": gen_normal, "dos": gen_dos,
              "bruteforce": gen_bruteforce, "sqli": gen_sqli, "exfil": gen_exfil}


# ─────────────────── Live-Mode Side Effects ────────────────────

class LiveEffects:
    """Mild real-HTTP effects for --mode live. Strictly a demo prop against a
    lab app — bounded rates, daemon threads, never blocks flow emission."""

    def __init__(self, target: str):
        self.target = target.rstrip("/")
        self.reachable = False
        self.sent = 0
        self.failed = 0
        self._warned = False
        self._stop = threading.Event()

    def _warn(self, msg: str) -> None:
        if not self._warned:
            print(f"   ⚠  live effects: {msg} — continuing to emit flows")
            self._warned = True

    def probe(self) -> None:
        try:
            requests.get(self.target, timeout=3)
            self.reachable = True
            print(f"   live target reachable: {self.target}")
        except requests.RequestException:
            self._warn(f"target {self.target} unreachable")

    def _spawn(self, fn) -> None:
        threading.Thread(target=self._guarded, args=(fn,), daemon=True).start()

    def _guarded(self, fn) -> None:
        try:
            fn()
            self.sent += 1
        except (requests.RequestException, OSError):
            self.failed += 1
            self._warn("request failed")

    def _dribble(self, until: float) -> None:
        """One slowloris-style connection: partial request + dribbled headers."""
        parsed = urlparse(self.target)
        if parsed.scheme not in ("http", "") or not parsed.hostname:
            self.failed += 1
            return self._warn("slowloris needs an http:// target")
        sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=5)
        sock.settimeout(5)
        sock.sendall(f"GET / HTTP/1.1\r\nHost: {parsed.hostname}\r\n".encode())
        i = 0
        while time.monotonic() < until and not self._stop.is_set():
            time.sleep(random.uniform(2.0, 5.0))
            i += 1
            sock.sendall(f"X-Dribble-{i}: {i}\r\n".encode())
        sock.close()

    def _exfil_download(self) -> None:
        with requests.get(self.target + "/", stream=True, timeout=10) as r:
            for _ in r.iter_content(8192):
                pass

    def on_phase_start(self, phase: str, until: float) -> None:
        if not self.reachable:
            return
        if phase == "dos":
            for _ in range(5):                      # small held-connection pool
                self._spawn(lambda: self._dribble(until))
        elif phase == "exfil":
            self._spawn(self._exfil_download)       # one large download

    def tick(self, phase: str) -> None:
        """~1 Hz per-tick real request matching the active phase."""
        if not self.reachable:
            return
        if phase in ("warmup", "cooldown"):
            if random.random() < 0.4:
                self._spawn(lambda: requests.get(self.target + "/", timeout=4))
        elif phase == "bruteforce":
            creds = {"username": f"user{random.randint(1, 999)}",
                     "password": f"pw-{uuid.uuid4().hex[:6]}"}
            self._spawn(lambda: requests.post(self.target + "/login", data=creds, timeout=4))
        elif phase == "sqli":
            q = random.choice(SQLI_STRINGS)
            self._spawn(lambda: requests.get(self.target + "/search", params={"q": q}, timeout=4))


# ─────────────────── Campaign Runner ───────────────────────────

def print_summary(stats: dict, live: "LiveEffects | None", t0: float) -> None:
    print("\n" + "═" * 58)
    print("  CAMPAIGN SUMMARY")
    print("═" * 58)
    print(f"  {'phase':<12}{'flows':>8}{'accepted':>10}{'rejected':>10}{'errors':>8}")
    for phase, s in stats.items():
        print(f"  {phase:<12}{s['flows']:>8}{s['accepted']:>10}{s['rejected']:>10}{s['errors']:>8}")
    if live is not None:
        print(f"  live effects : {live.sent} requests sent, {live.failed} failed")
    print(f"  elapsed      : {time.monotonic() - t0:.1f} s")
    print("═" * 58)


def run_campaign(args) -> int:
    phases = SCENARIOS[args.scenario]
    tag = not args.no_lbl_tag
    batch_n = max(1, args.batch_size)
    interval = batch_n / max(args.rate, 0.1)

    session = requests.Session()
    session.headers.update({"X-Sensor-Key": args.key, "Content-Type": "application/json"})

    live = None
    if args.mode == "live":
        if not args.target:
            print("   ⚠  --mode live needs --target; running ingest-only")
        else:
            live = LiveEffects(args.target)
            live.probe()

    stats = {p: {"flows": 0, "accepted": 0, "rejected": 0, "errors": 0, "batches": 0}
             for p in phases}
    t0 = time.monotonic()

    print("=" * 58)
    print("  CyberAdapt Attack Campaign")
    print(f"  Scenario  : {args.scenario}  ({' → '.join(phases)})")
    print(f"  Mode      : {args.mode}   Rate: {args.rate} flows/s   "
          f"Batch: {batch_n}   LBL tags: {'on' if tag else 'OFF'}")
    print(f"  Ingest    : {args.url}")
    print("=" * 58)

    try:
        for phase in phases:
            dur = PHASE_SECONDS[phase] * args.scale
            end = time.monotonic() + dur
            s = stats[phase]
            sensor_id = f"attack-campaign-{phase}"
            print(f"\n═══ PHASE: {phase} — {dur:.0f} s  (sensor_id={sensor_id}) ═══")
            if live:
                live.on_phase_start(phase, end)

            while time.monotonic() < end:
                tick0 = time.monotonic()
                flows = [GENERATORS[phase](phase, tag) for _ in range(batch_n)]
                payload = {"sensor_id": sensor_id,
                           "batch_timestamp": int(time.time() * 1000),
                           "flow_count": len(flows), "flows": flows}
                s["batches"] += 1
                s["flows"] += len(flows)
                try:
                    res = session.post(args.url, json=payload, timeout=5)
                    if res.status_code in (200, 202):
                        s["accepted"] += res.json().get("accepted", len(flows))
                        s["rejected"] += res.json().get("rejected", 0)
                    else:
                        s["errors"] += 1
                        if s["errors"] <= 3 or s["errors"] % 10 == 0:
                            print(f"   [{phase} +{time.monotonic()-t0:5.1f}s] "
                                  f"HTTP {res.status_code}: {res.text[:100]}")
                except requests.RequestException as e:
                    s["errors"] += 1
                    if s["errors"] <= 3 or s["errors"] % 10 == 0:
                        print(f"   [{phase} +{time.monotonic()-t0:5.1f}s] "
                              f"ingest error: {type(e).__name__}")

                if live:
                    live.tick(phase)
                elapsed = time.monotonic() - tick0
                if elapsed < interval:
                    time.sleep(interval - elapsed)

            print(f"   → {phase}: {s['flows']} flows in {s['batches']} batches, "
                  f"{s['accepted']} accepted, {s['errors']} errors")
    except KeyboardInterrupt:
        print("\n\n⏹  Ctrl+C — stopping campaign")
    finally:
        if live:
            live._stop.set()

    print_summary(stats, live, t0)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="CyberAdapt phased attack campaign")
    parser.add_argument("--key", default=os.environ.get("SENSOR_KEY", ""),
                        help="Sensor API key (or SENSOR_KEY env)")
    parser.add_argument("--url", default=os.environ.get("INGEST_URL", INGEST_URL),
                        help="Backend ingest endpoint")
    parser.add_argument("--mode", choices=["ingest", "live"], default="ingest",
                        help="ingest = flows only; live = + real HTTP at --target")
    parser.add_argument("--target", default="",
                        help="Lab app base URL for --mode live (e.g. http://localhost:3000)")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="mixed",
                        help="mixed = full 6-phase run; others = warmup/attack/cooldown")
    parser.add_argument("--rate", type=float, default=6.0, help="Flows per second")
    parser.add_argument("--batch-size", type=int, default=6, help="Flows per POST")
    parser.add_argument("--scale", type=float, default=1.0,
                        help="Phase-duration multiplier (e.g. 0.2 = quick smoke run)")
    parser.add_argument("--no-lbl-tag", action="store_true",
                        help="Emit untagged flow_ids (pure pseudo-label experiment)")
    args = parser.parse_args()

    if not args.key:
        print("ERROR: --key or SENSOR_KEY env var is required")
        print("Run: node scripts/seed-dev.js  (in server/) to generate one")
        sys.exit(1)

    sys.exit(run_campaign(args))


if __name__ == "__main__":
    main()
