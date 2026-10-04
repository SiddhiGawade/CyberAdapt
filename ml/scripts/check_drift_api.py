"""TASK-11 verification helper — polls /concept-drift and audits the §8 contract.

Usage:
  python ml/scripts/check_drift_api.py once          # one compact status line
  python ml/scripts/check_drift_api.py poll [int]    # status line every <int> s (default 2)
  python ml/scripts/check_drift_api.py audit         # field-by-field §8 contract audit
  python ml/scripts/check_drift_api.py full          # pretty-print the raw JSON

ASCII-only output (cp1252 consoles).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(errors="replace")

BASE = "http://127.0.0.1:5001"


def get_status() -> dict:
    with urllib.request.urlopen(f"{BASE}/concept-drift", timeout=5) as r:
        return json.loads(r.read().decode())


def short(s: dict) -> str:
    det = s["detector_algorithms"]
    psi = {f["slot"]: f["drift"] for f in s["labrooms_features_drift"]}
    sig = (
        f"ADWIN={det['ADWIN_attack_ratio']['drift_signal']} "
        f"PH={det['PageHinkley']['drift_signal']} "
        f"DDM={det['DDM_pseudo_error']['drift_signal']} "
        f"KS={det['KS_Test']['drift_signal']}"
    )
    psis = " ".join(f"s{k}={v:.4f}" for k, v in psi.items())
    return (
        f"status={s['status']} drift_state={s['drift_state']} det={s['drift_detected']} "
        f"n={s['samples_processed']} n_since={s['samples_processed_since_retrain']} "
        f"atk_ratio={s['attack_ratio_recent']:.4f} events={len(s['drift_events'])} | {sig} | {psis}"
    )


def audit() -> int:
    s = get_status()
    ok = True

    def check(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok
        mark = "OK " if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{mark}] {name}{(' — ' + extra) if extra else ''}")

    print("== §8 /concept-drift contract audit (live JSON) ==")

    # Top-level keys: exact contract set
    expected = {
        "status", "drift_detected", "drift_state", "samples_processed",
        "samples_processed_since_retrain", "last_drift_timestamp",
        "attack_ratio_recent", "detector_algorithms",
        "labrooms_features_drift", "drift_events",
    }
    got = set(s.keys())
    check("top-level keys exact", got == expected,
          f"missing={sorted(expected - got)} extra={sorted(got - expected)}")

    check("status str in {warming_up,active}",
          isinstance(s["status"], str) and s["status"] in ("warming_up", "active"),
          s["status"])
    check("drift_detected bool", isinstance(s["drift_detected"], bool))
    check("drift_state in {stable,warning,drift}",
          s["drift_state"] in ("stable", "warning", "drift"), s["drift_state"])
    check("samples_processed int >= 0",
          isinstance(s["samples_processed"], int) and s["samples_processed"] >= 0,
          str(s["samples_processed"]))
    check("samples_processed_since_retrain int >= 0",
          isinstance(s["samples_processed_since_retrain"], int)
          and s["samples_processed_since_retrain"] >= 0)
    ldt = s["last_drift_timestamp"]
    check("last_drift_timestamp str-or-null",
          ldt is None or isinstance(ldt, str), str(ldt))
    check("attack_ratio_recent float 0..1",
          isinstance(s["attack_ratio_recent"], (int, float))
          and 0.0 <= s["attack_ratio_recent"] <= 1.0,
          str(s["attack_ratio_recent"]))

    # detector_algorithms — 4 named entries with per-detector keys
    det = s["detector_algorithms"]
    check("detector_algorithms keys",
          set(det.keys()) == {"ADWIN_attack_ratio", "PageHinkley",
                              "DDM_pseudo_error", "KS_Test"},
          str(sorted(det.keys())))
    a = det["ADWIN_attack_ratio"]
    check("ADWIN keys {status,estimation,width,drift_signal}",
          set(a.keys()) == {"status", "estimation", "width", "drift_signal"})
    check("ADWIN types", isinstance(a["estimation"], (int, float))
          and isinstance(a["width"], int) and isinstance(a["drift_signal"], bool))
    p = det["PageHinkley"]
    check("PageHinkley keys {status,sum_val,threshold,drift_signal}",
          set(p.keys()) == {"status", "sum_val", "threshold", "drift_signal"})
    check("PageHinkley types", isinstance(p["sum_val"], (int, float))
          and isinstance(p["threshold"], (int, float))
          and isinstance(p["drift_signal"], bool))
    d = det["DDM_pseudo_error"]
    check("DDM keys {status,error_rate,warning_level,drift_signal}",
          set(d.keys()) == {"status", "error_rate", "warning_level", "drift_signal"})
    check("DDM types", isinstance(d["error_rate"], (int, float))
          and (d["warning_level"] is None or isinstance(d["warning_level"], (int, float)))
          and isinstance(d["drift_signal"], bool))
    k = det["KS_Test"]
    check("KS keys {status,stat,p_value,drift_signal}",
          set(k.keys()) == {"status", "stat", "p_value", "drift_signal"})
    check("KS types", (k["stat"] is None or isinstance(k["stat"], (int, float)))
          and (k["p_value"] is None or isinstance(k["p_value"], (int, float)))
          and isinstance(k["drift_signal"], bool))

    # labrooms_features_drift — exactly the 5 contract slots
    feats = s["labrooms_features_drift"]
    check("features list len 5", isinstance(feats, list) and len(feats) == 5)
    exp_slots = {1: "Flow Duration", 4: "Total Fwd Bytes", 5: "Total Bwd Bytes",
                 14: "Flow Bytes/s", 44: "HTTP Status Code"}
    if isinstance(feats, list):
        for f in feats:
            check(f"slot {f.get('slot')} keys+types",
                  set(f.keys()) == {"slot", "name", "drift", "status"}
                  and f["name"] == exp_slots.get(f["slot"])
                  and isinstance(f["drift"], (int, float))
                  and f["status"] in ("stable", "minor_shift", "drifted"),
                  json.dumps(f))

    # drift_events — cap 20, newest first, event shape
    ev = s["drift_events"]
    check("drift_events list <=20", isinstance(ev, list) and len(ev) <= 20)
    if ev:
        keys_ok = all(set(e.keys()) == {"timestamp", "signal", "detector",
                                        "samples_processed", "detail"}
                      for e in ev)
        check("event keys {timestamp,signal,detector,samples_processed,detail}", keys_ok)
        ts = [e["timestamp"] for e in ev]
        check("events newest-first", ts == sorted(ts, reverse=True), str(ts[:3]))
        check("event types", all(isinstance(e["samples_processed"], int)
                                 and isinstance(e["detail"], str)
                                 and isinstance(e["signal"], str)
                                 and isinstance(e["detector"], str)
                                 and isinstance(e["timestamp"], str) for e in ev))

    print("== audit %s ==" % ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "audit":
        return audit()
    if mode == "full":
        print(json.dumps(get_status(), indent=2, sort_keys=True))
        return 0
    if mode == "poll":
        interval = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
        i = 0
        try:
            while True:
                i += 1
                print(f"[{i:04d}] {short(get_status())}", flush=True)
                time.sleep(interval)
        except KeyboardInterrupt:
            return 0
    print(short(get_status()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
