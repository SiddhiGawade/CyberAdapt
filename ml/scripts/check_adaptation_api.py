"""TASK-12 verification helper — polls /adaptation, audits the §8 contract,
drives triggers/reset, and seeds labeled flows through the real ingest path.

Usage (from repo root, .venv python):
  python ml/scripts/check_adaptation_api.py status        # compact status line
  python ml/scripts/check_adaptation_api.py poll [int]    # every <int> s (def 2)
  python ml/scripts/check_adaptation_api.py audit         # §8 field-by-field audit
  python ml/scripts/check_adaptation_api.py full          # raw /adaptation JSON
  python ml/scripts/check_adaptation_api.py modelinfo     # GET /model-info
  python ml/scripts/check_adaptation_api.py trigger       # POST /adaptation/trigger (Flask)
  python ml/scripts/check_adaptation_api.py triggerx2     # two immediate triggers
  python ml/scripts/check_adaptation_api.py proxytrigger          # via Node + JWT
  python ml/scripts/check_adaptation_api.py proxytriggerx2        # via Node + JWT x2
  python ml/scripts/check_adaptation_api.py reset         # POST /admin/reset
  python ml/scripts/check_adaptation_api.py seed dos|normal N [batch]  # N flows via Node ingest
  python ml/scripts/check_adaptation_api.py predict dos|normal N       # N flows via Flask /predict
  python ml/scripts/check_adaptation_api.py waitpromo [timeout_s]      # poll until version != v1

Env overrides: FLASK_URL (default http://127.0.0.1:5001), NODE_URL
(default http://127.0.0.1:5000), SENSOR_KEY, LOGIN_EMAIL, LOGIN_PASSWORD.

ASCII-only output (cp1252 consoles).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

FLASK = "http://127.0.0.1:5001"
NODE = "http://127.0.0.1:5000"
SENSOR_KEY = "ca_live_5d1483088f28ea9b364ad89d30adf66f797fc7004d4c5543523a6ac0b3391b6a"
LOGIN_EMAIL = "admin@acme-test.local"
LOGIN_PASSWORD = "Test@1234"

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "sensor"))
import attack_campaign as ac  # noqa: E402  real generator envelopes

EXPECTED_KEYS = {
    "champion_model", "champion_version", "adaptation_mode", "model_loaded_at",
    "adaptation_in_progress", "online_learning_buffer", "retraining_history",
    "last_event",
}
EXPECTED_LABEL_SOURCES = {"rule_override", "high_confidence", "flow_id_tag"}
EXPECTED_GATES = {"gate_macro_f1", "gate_bal_acc", "gate_emerged_recall", "gate_normal_fpr"}
EXPECTED_EVENT_TYPES = {"promotion", "rejection", "skipped", "error"}
EXPECTED_HIST_KEYS = {"version", "timestamp", "f1_score", "trigger", "promoted", "gates_passed"}
EXPECTED_EVENT_KEYS = {"type", "timestamp", "detail"}


def _req(method: str, url: str, body: dict | None = None,
         headers: dict | None = None, timeout: float = 8.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "null")
        except Exception:
            return e.code, {"_raw": "unparseable"}


def get_adaptation() -> dict:
    return _req("GET", f"{FLASK}/adaptation")[1]


def get_drift() -> dict:
    return _req("GET", f"{FLASK}/concept-drift")[1]


def get_model_info() -> dict:
    return _req("GET", f"{FLASK}/model-info")[1]


def login_jwt() -> str:
    code, body = _req("POST", f"{NODE}/api/auth/login",
                      {"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD})
    if code != 200 or not isinstance(body, dict) or "token" not in body:
        print(f"[login] FAIL HTTP {code}: {body}")
        sys.exit(2)
    return body["token"]


def short() -> str:
    a = get_adaptation()
    buf = a.get("online_learning_buffer", {})
    ls = buf.get("label_sources", {})
    hist = a.get("retraining_history", [])
    le = a.get("last_event") or {}
    try:
        d = get_drift()
        drift = (f"drift_state={d.get('drift_state')} n={d.get('samples_processed')} "
                 f"events={len(d.get('drift_events', []))} atk={d.get('attack_ratio_recent'):.3f}")
    except Exception:
        drift = "drift=? (api down?)"
    return (
        f"version={a.get('champion_version')} in_progress={a.get('adaptation_in_progress')} "
        f"buffer={buf.get('current_size')}/{buf.get('capacity')} ({buf.get('fill_percentage')}%) "
        f"labels=[ro:{ls.get('rule_override')} hc:{ls.get('high_confidence')} "
        f"tag:{ls.get('flow_id_tag')}] hist={len(hist)} "
        f"last_event={le.get('type')}: {str(le.get('detail'))[:110]} | {drift}"
    )


def poll(interval: float) -> None:
    while True:
        print(f"[{time.strftime('%H:%M:%S')}] {short()}")
        time.sleep(interval)


def waitpromo(timeout_s: float) -> int:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        a = get_adaptation()
        le = a.get("last_event") or {}
        print(f"[+{time.time() - t0:5.1f}s] {short()}")
        if a.get("champion_version") != "v1":
            print(f"PROMOTED -> {a.get('champion_version')} in {time.time() - t0:.1f}s")
            return 0
        if le.get("type") in ("rejection", "error") and not a.get("adaptation_in_progress"):
            print(f"TERMINAL EVENT {le.get('type')} — no promotion")
            return 3
        time.sleep(1.5)
    print(f"TIMEOUT after {timeout_s}s — no promotion")
    return 4


def _flow_batch(kind: str, n: int) -> list:
    gen = {"dos": ac.gen_dos, "normal": ac.gen_normal,
           "bruteforce": ac.gen_bruteforce, "sqli": ac.gen_sqli}[kind]
    return [gen("seed", True) for _ in range(n)]


def seed(kind: str, total: int, batch: int) -> int:
    """Send flows through the REAL ingest path (Node -> Mongo -> Flask /predict)."""
    sent = 0
    while sent < total:
        n = min(batch, total - sent)
        flows = _flow_batch(kind, n)
        code, body = _req("POST", f"{NODE}/api/telemetry/ingest",
                          {"sensor_id": "t12-seed", "batch_timestamp": int(time.time() * 1000),
                           "flow_count": len(flows), "flows": flows},
                          headers={"X-Sensor-Key": SENSOR_KEY})
        print(f"[seed {kind}] +{n} via ingest -> HTTP {code} accepted={body.get('accepted')}")
        if code not in (200, 202):
            return 2
        sent += n
        time.sleep(0.7)  # let fire-and-forget /predict land
        print("   ", short())
    return 0


def predict_direct(kind: str, total: int, batch: int = 50) -> int:
    """Send flows straight to Flask /predict (craft path)."""
    sent = 0
    while sent < total:
        n = min(batch, total - sent)
        flows = _flow_batch(kind, n)
        code, body = _req("POST", f"{FLASK}/predict", {"flows": flows})
        labels = {}
        for p in (body.get("predictions") or []):
            labels[p["label"]] = labels.get(p["label"], 0) + 1
        print(f"[predict {kind}] +{n} -> HTTP {code} labels={labels} lat={body.get('latency_ms')}ms")
        sent += n
    print("   ", short())
    return 0


def trigger() -> int:
    code, body = _req("POST", f"{FLASK}/adaptation/trigger")
    print(f"[trigger flask] -> HTTP {code} {json.dumps(body)}")
    return 0


def triggerx2() -> int:
    code1, body1 = _req("POST", f"{FLASK}/adaptation/trigger")
    code2, body2 = _req("POST", f"{FLASK}/adaptation/trigger")
    print(f"[trigger flask #1] -> HTTP {code1} {json.dumps(body1)}")
    print(f"[trigger flask #2] -> HTTP {code2} {json.dumps(body2)}")
    return 0


def proxytrigger(times: int = 1) -> int:
    tok = login_jwt()
    print(f"[login] JWT ok ({len(tok)} chars)")
    for i in range(times):
        code, body = _req("POST", f"{NODE}/api/telemetry/adaptation/trigger",
                          headers={"Authorization": f"Bearer {tok}"})
        print(f"[trigger node #{i + 1}] -> HTTP {code} {json.dumps(body)}")
    return 0


def reset() -> int:
    code, body = _req("POST", f"{FLASK}/admin/reset")
    print(f"[reset] -> HTTP {code} {json.dumps(body)}")
    print("   ", short())
    return 0


def modelinfo() -> int:
    code, body = _req("GET", f"{FLASK}/model-info")
    print(f"[model-info] -> HTTP {code} {json.dumps(body)}")
    return 0


def audit() -> int:
    a = get_adaptation()
    ok = True

    def check(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok
        mark = "OK " if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{mark}] {name}{(' — ' + extra) if extra else ''}")

    print("== §8 /adaptation contract audit (live JSON) ==")
    check("top-level keys exact §8 set", set(a.keys()) == EXPECTED_KEYS,
          f"got {sorted(a.keys())}")
    check("champion_model str", isinstance(a.get("champion_model"), str), a.get("champion_model"))
    check("champion_version str vN", isinstance(a.get("champion_version"), str)
          and a["champion_version"].startswith("v"), a.get("champion_version"))
    check("adaptation_mode str", isinstance(a.get("adaptation_mode"), str))
    check("model_loaded_at ISO str", isinstance(a.get("model_loaded_at"), str)
          and "T" in a["model_loaded_at"], a.get("model_loaded_at"))
    check("adaptation_in_progress bool", isinstance(a.get("adaptation_in_progress"), bool))

    buf = a.get("online_learning_buffer", {})
    check("online_learning_buffer keys",
          set(buf.keys()) == {"capacity", "current_size", "fill_percentage", "label_sources"},
          f"got {sorted(buf.keys())}")
    check("buffer.capacity int>0", isinstance(buf.get("capacity"), int) and buf["capacity"] > 0,
          str(buf.get("capacity")))
    check("buffer.current_size int>=0", isinstance(buf.get("current_size"), int)
          and buf["current_size"] >= 0, str(buf.get("current_size")))
    check("buffer.fill_percentage float", isinstance(buf.get("fill_percentage"), (int, float)))
    ls = buf.get("label_sources", {})
    check("label_sources keys exact", set(ls.keys()) == EXPECTED_LABEL_SOURCES,
          f"got {sorted(ls.keys())}")
    check("label_sources all int>=0",
          all(isinstance(v, int) and v >= 0 for v in ls.values()), str(ls))

    hist = a.get("retraining_history", [])
    check("retraining_history list", isinstance(hist, list))
    for i, h in enumerate(hist):
        check(f"hist[{i}] keys exact", set(h.keys()) == EXPECTED_HIST_KEYS, f"got {sorted(h.keys())}")
        check(f"hist[{i}].promoted bool", isinstance(h.get("promoted"), bool), str(h.get("promoted")))
        check(f"hist[{i}].f1_score number", isinstance(h.get("f1_score"), (int, float)),
              str(h.get("f1_score")))
        check(f"hist[{i}].version str", isinstance(h.get("version"), str), str(h.get("version")))
        gp = h.get("gates_passed", {})
        check(f"hist[{i}].gates_passed keys", set(gp.keys()) == EXPECTED_GATES,
              f"got {sorted(gp.keys()) if isinstance(gp, dict) else gp}")
        check(f"hist[{i}].gates all bool",
              isinstance(gp, dict) and all(isinstance(v, bool) for v in gp.values()))

    le = a.get("last_event")
    if le is None:
        check("last_event null-or-dict", True, "null (no events yet)")
    else:
        check("last_event keys exact", set(le.keys()) == EXPECTED_EVENT_KEYS,
              f"got {sorted(le.keys())}")
        check("last_event.type vocab", le.get("type") in EXPECTED_EVENT_TYPES, str(le.get("type")))
        check("last_event.timestamp str", isinstance(le.get("timestamp"), str))
        check("last_event.detail str", isinstance(le.get("detail"), str))

    print(f"== audit {'PASSED' if ok else 'FAILED'} ==")
    return 0 if ok else 1


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(short()); return 0
    if cmd == "poll":
        poll(float(sys.argv[2]) if len(sys.argv) > 2 else 2.0); return 0
    if cmd == "audit":
        return audit()
    if cmd == "full":
        print(json.dumps(get_adaptation(), indent=2)); return 0
    if cmd == "drift":
        print(json.dumps(get_drift(), indent=2)); return 0
    if cmd == "modelinfo":
        return modelinfo()
    if cmd == "trigger":
        return trigger()
    if cmd == "triggerx2":
        return triggerx2()
    if cmd == "proxytrigger":
        return proxytrigger(1)
    if cmd == "proxytriggerx2":
        return proxytrigger(2)
    if cmd == "reset":
        return reset()
    if cmd == "seed":
        return seed(sys.argv[2], int(sys.argv[3]),
                    int(sys.argv[4]) if len(sys.argv) > 4 else 30)
    if cmd == "predict":
        return predict_direct(sys.argv[2], int(sys.argv[3]),
                              int(sys.argv[4]) if len(sys.argv) > 4 else 50)
    if cmd == "waitpromo":
        return waitpromo(float(sys.argv[2]) if len(sys.argv) > 2 else 120)
    print(f"unknown cmd {cmd}"); return 2


if __name__ == "__main__":
    sys.exit(main())
