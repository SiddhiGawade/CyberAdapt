"""TASK-13 verification helper — snapshots + §8 field-by-field contract audit
for GET /evaluation on the live Flask stack.

Usage (from repo root, .venv python):
  python ml/scripts/check_evaluation_api.py snap [label]   # compact snapshot
  python ml/scripts/check_evaluation_api.py full           # raw JSON
  python ml/scripts/check_evaluation_api.py audit          # §8 contract audit
  python ml/scripts/check_evaluation_api.py reset          # /admin/reset + snap
  python ml/scripts/check_evaluation_api.py file           # eval_window.jsonl stats

Env overrides: FLASK_URL (default http://127.0.0.1:5001).

ASCII-only output (cp1252 consoles). Verify-only: touches no ml/api.py or
ml/src/* — this is a read-only client plus /admin/reset.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

FLASK = "http://127.0.0.1:5001"
REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_FILE = REPO_ROOT / "ml" / "artifacts" / "state" / "eval_window.jsonl"
HIST_FILE = REPO_ROOT / "ml" / "artifacts" / "state" / "adaptation_history.json"

EXPECTED_TOP = {"dataset", "window", "overall_metrics", "per_class_metrics",
                "confusion_matrix", "class_names", "pre_post_adaptation"}
EXPECTED_CLASS_NAMES = ["Normal Traffic", "DoS", "DDoS", "Port Scanning",
                        "Brute Force", "Web Attacks", "Bots"]
EXPECTED_WINDOW_KEYS = {"size", "capacity", "since"}
EXPECTED_OVERALL_KEYS = {"accuracy", "precision_macro", "recall_macro",
                         "f1_macro", "latency_p95_ms"}
EXPECTED_PER_CLASS_KEYS = {"precision", "recall", "f1", "support"}
EXPECTED_PREPOST_KEYS = {"pre", "post", "last_adaptation"}
EXPECTED_SPLIT_KEYS = {"f1_macro", "samples"}
DATASET_LABEL = "Live Labrooms stream (pseudo-labeled)"


def _req(method: str, url: str, body: dict | None = None,
         headers: dict | None = None, timeout: float = 10.0):
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


def get_eval() -> dict:
    return _req("GET", f"{FLASK}/evaluation")[1]


def get_drift() -> dict:
    return _req("GET", f"{FLASK}/concept-drift")[1]


def get_adaptation() -> dict:
    return _req("GET", f"{FLASK}/adaptation")[1]


def _cm_stats(m: dict):
    """Return (row0_diag, row0_offdiag, total_offdiag, total) from the matrix."""
    cm = m.get("confusion_matrix") or []
    total = sum(sum(r) for r in cm if isinstance(r, list))
    row0 = cm[0] if cm and isinstance(cm[0], list) else []
    r0d = row0[0] if row0 else 0
    r0off = sum(row0[1:]) if len(row0) > 1 else 0
    off = total - sum(cm[i][i] for i in range(min(len(cm), 7))
                      if isinstance(cm[i], list) and len(cm[i]) > i)
    return r0d, r0off, off, total


def snap(label: str = "") -> int:
    m = get_eval()
    win = m.get("window", {})
    om = m.get("overall_metrics", {})
    r0d, r0off, off, total = _cm_stats(m)
    supports = {k: v.get("support") for k, v in
                (m.get("per_class_metrics") or {}).items() if v.get("support")}
    pp = m.get("pre_post_adaptation") or {}
    pre, post = pp.get("pre") or {}, pp.get("post")
    pre_s = f"pre=f1:{pre.get('f1_macro'):.4f}/n:{pre.get('samples')}" \
        if isinstance(pre.get("f1_macro"), (int, float)) else f"pre={pre}"
    post_s = (f"post=f1:{post.get('f1_macro'):.4f}/n:{post.get('samples')}"
              if isinstance(post, dict) else "post=None")
    try:
        a = get_adaptation()
        ver = a.get("champion_version")
    except Exception:
        ver = "?"
    tag = f"[{label}] " if label else ""
    print(f"{tag}size={win.get('size')}/{win.get('capacity')} "
          f"since={win.get('since')} insuff={m.get('insufficient_data', False)}")
    print(f"   acc={om.get('accuracy'):.4f} p={om.get('precision_macro'):.4f} "
          f"r={om.get('recall_macro'):.4f} f1={om.get('f1_macro'):.4f} "
          f"p95={om.get('latency_p95_ms'):.2f}ms")
    print(f"   cm: row0 diag={r0d} off={r0off} | total={total} offdiag={off}")
    print(f"   support={supports}")
    print(f"   pre_post: {pre_s} {post_s} last={pp.get('last_adaptation')}")
    print(f"   champion={ver}")
    return 0


def audit() -> int:
    m = get_eval()
    ok = True

    def check(name: str, cond: bool, extra: str = "") -> None:
        nonlocal ok
        mark = "OK " if cond else "FAIL"
        if not cond:
            ok = False
        print(f"  [{mark}] {name}{(' — ' + str(extra)) if extra else ''}")

    print("== §8 /evaluation contract audit (live JSON) ==")
    top = set(m.keys())
    check("top-level keys ⊆ §8 set (+insufficient_data allowed)",
          top <= (EXPECTED_TOP | {"insufficient_data"}), f"got {sorted(top)}")
    check("top-level keys ⊇ §8 set", top >= EXPECTED_TOP,
          f"missing {sorted(EXPECTED_TOP - top)}")

    check('dataset == "Live Labrooms stream (pseudo-labeled)"',
          m.get("dataset") == DATASET_LABEL, m.get("dataset"))

    win = m.get("window", {})
    check("window keys {size,capacity,since}",
          set(win.keys()) == EXPECTED_WINDOW_KEYS, f"got {sorted(win.keys())}")
    check("window.size int 0..capacity",
          isinstance(win.get("size"), int)
          and 0 <= win["size"] <= (win.get("capacity") or 0),
          f"{win.get('size')}/{win.get('capacity')}")
    check("window.capacity int==500", win.get("capacity") == 500,
          win.get("capacity"))
    check("window.since ISO str or null",
          win.get("since") is None or isinstance(win.get("since"), str),
          win.get("since"))

    om = m.get("overall_metrics", {})
    check("overall_metrics keys exact",
          set(om.keys()) == EXPECTED_OVERALL_KEYS, f"got {sorted(om.keys())}")
    for k in ("accuracy", "precision_macro", "recall_macro", "f1_macro"):
        v = om.get(k)
        check(f"overall.{k} float in [0,1]",
              isinstance(v, (int, float)) and 0.0 <= v <= 1.0, v)
    check("overall.latency_p95_ms float >=0",
          isinstance(om.get("latency_p95_ms"), (int, float))
          and om["latency_p95_ms"] >= 0.0, om.get("latency_p95_ms"))

    pc = m.get("per_class_metrics", {})
    check("per_class_metrics dict", isinstance(pc, dict))
    check("per_class keys ⊆ class_names",
          set(pc.keys()) <= set(EXPECTED_CLASS_NAMES),
          f"extra {sorted(set(pc.keys()) - set(EXPECTED_CLASS_NAMES))}")
    for cls, met in pc.items():
        check(f"per_class[{cls}] keys exact",
              isinstance(met, dict) and set(met.keys()) == EXPECTED_PER_CLASS_KEYS,
              f"got {sorted(met.keys()) if isinstance(met, dict) else met}")
        if isinstance(met, dict):
            nums = all(isinstance(met.get(k), (int, float))
                       for k in ("precision", "recall", "f1"))
            check(f"per_class[{cls}] p/r/f1 numeric", nums)
            check(f"per_class[{cls}].support int>=0",
                  isinstance(met.get("support"), int) and met["support"] >= 0,
                  met.get("support"))

    cm = m.get("confusion_matrix")
    check("confusion_matrix 7 rows",
          isinstance(cm, list) and len(cm) == 7,
          f"{len(cm) if isinstance(cm, list) else type(cm)} rows")
    rows_ok = isinstance(cm, list) and all(
        isinstance(r, list) and len(r) == 7
        and all(isinstance(c, int) and c >= 0 for c in r) for r in cm)
    check("confusion_matrix 7x7 non-negative ints", rows_ok)
    _, _, _, cm_total = _cm_stats(m)
    check("confusion_matrix total == window.size",
          cm_total == win.get("size"), f"{cm_total} vs {win.get('size')}")

    check("class_names exact §8 order",
          m.get("class_names") == EXPECTED_CLASS_NAMES, m.get("class_names"))

    pp = m.get("pre_post_adaptation", {})
    check("pre_post_adaptation keys exact",
          isinstance(pp, dict) and set(pp.keys()) == EXPECTED_PREPOST_KEYS,
          f"got {sorted(pp.keys()) if isinstance(pp, dict) else pp}")
    pre = pp.get("pre") if isinstance(pp, dict) else None
    post = pp.get("post") if isinstance(pp, dict) else None
    check("pre block {f1_macro,samples}",
          isinstance(pre, dict) and set(pre.keys()) == EXPECTED_SPLIT_KEYS,
          f"got {sorted(pre.keys()) if isinstance(pre, dict) else pre}")
    if isinstance(pre, dict):
        check("pre.f1_macro float", isinstance(pre.get("f1_macro"), (int, float)),
              pre.get("f1_macro"))
        check("pre.samples int>=0",
              isinstance(pre.get("samples"), int) and pre["samples"] >= 0,
              pre.get("samples"))
    check("post null or {f1_macro,samples}",
          post is None or (isinstance(post, dict)
                           and set(post.keys()) == EXPECTED_SPLIT_KEYS),
          post if not isinstance(post, dict) else "dict ok")
    if isinstance(post, dict):
        check("post.f1_macro float", isinstance(post.get("f1_macro"), (int, float)))
        check("post.samples int>=0",
              isinstance(post.get("samples"), int) and post["samples"] >= 0)
        pre_n = pre.get("samples", 0) if isinstance(pre, dict) else 0
        check("pre.samples + post.samples == window.size",
              pre_n + post["samples"] == win.get("size"),
              f"{pre_n}+{post['samples']} vs {win.get('size')}")
    la = pp.get("last_adaptation") if isinstance(pp, dict) else "?"
    check("last_adaptation ISO str or null",
          la is None or isinstance(la, str), la)
    check("post!=null iff last_adaptation!=null",
          (post is not None) == (la is not None),
          f"post={'set' if post else 'null'} last={la}")

    size = win.get("size", 0)
    if size < 30:
        check("insufficient_data present+true when size<30",
          m.get("insufficient_data") is True, m.get("insufficient_data"))
    else:
        check("insufficient_data absent/false when size>=30",
          m.get("insufficient_data") in (None, False),
          m.get("insufficient_data"))

    # cross-check support totals vs window size
    sup_total = sum(v.get("support", 0) for v in pc.values()
                    if isinstance(v, dict))
    check("sum(per_class.support) == window.size",
          sup_total == win.get("size"), f"{sup_total} vs {win.get('size')}")

    print(f"== audit {'PASSED' if ok else 'FAILED'} ==")
    return 0 if ok else 1


def file_stats() -> int:
    if not EVAL_FILE.exists():
        print(f"[file] {EVAL_FILE} MISSING")
    else:
        lines = EVAL_FILE.read_text(encoding="utf-8").splitlines()
        lines = [ln for ln in lines if ln.strip()]
        ok_rows = 0
        versions = {}
        for ln in lines:
            try:
                r = json.loads(ln)
                ok_rows += 1
                versions[r.get("version")] = versions.get(r.get("version"), 0) + 1
            except json.JSONDecodeError:
                pass
        print(f"[file] {EVAL_FILE.name}: {len(lines)} lines, {ok_rows} parseable, "
              f"versions={versions}")
        if lines:
            print(f"[file] first row: {lines[0][:160]}")
    if HIST_FILE.exists():
        try:
            h = json.loads(HIST_FILE.read_text(encoding="utf-8"))
            promos = [e for e in h if isinstance(e, dict) and e.get("promoted")]
            print(f"[file] adaptation_history.json: {len(h)} entries, "
                  f"{len(promos)} promoted; last_promoted_ts="
                  f"{promos[-1].get('timestamp') if promos else None}")
        except Exception as e:
            print(f"[file] adaptation_history.json unreadable: {e}")
    else:
        print(f"[file] {HIST_FILE.name} MISSING")
    return 0


def reset() -> int:
    code, body = _req("POST", f"{FLASK}/admin/reset")
    print(f"[reset] -> HTTP {code} {json.dumps(body)}")
    return snap("post-reset")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snap"
    if cmd == "snap":
        return snap(sys.argv[2] if len(sys.argv) > 2 else "")
    if cmd == "full":
        print(json.dumps(get_eval(), indent=2)); return 0
    if cmd == "audit":
        return audit()
    if cmd == "reset":
        return reset()
    if cmd == "file":
        return file_stats()
    print(f"unknown cmd {cmd}"); return 2


if __name__ == "__main__":
    sys.exit(main())
