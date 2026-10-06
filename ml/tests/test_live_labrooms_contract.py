from __future__ import annotations

from ml.src.adaptation.live_adapter import LiveAdapter, _default_extract_features
from ml.src.evaluation.live_evaluator import _resolve_pseudo_label
from ml.src.features.feature_contract import LABROOMS_DEPLOYMENT_FEATURES, TARGET_CLASSES
from ml import api as ml_api


def _new_adapter(tmp_path, *, events=None, min_buffer=200, min_attack=30):
    queued_events = events if events is not None else []
    return LiveAdapter(
        state_dir=tmp_path,
        get_champion=lambda: (None, None),
        set_champion=lambda _model, _preprocessor, _version: None,
        extract_features=_default_extract_features,
        consume_drift_event=lambda: queued_events.pop(0) if queued_events else None,
        reset_drift_reference=lambda: None,
        min_buffer=min_buffer,
        min_attack=min_attack,
        cooldown_sec=0,
    )


def _record(*, flow_id="ordinary-flow", label="Normal Traffic", label_index=0,
            confidence=0.99, rule_override=False, ground_truth_label=None):
    return {
        "flow_id": flow_id,
        "raw_features": [float(index) for index in range(52)],
        "label": label,
        "label_index": label_index,
        "confidence": confidence,
        "rule_override": rule_override,
        "ground_truth_label": ground_truth_label,
    }


def test_labrooms_model_features_map_to_correct_slots():
    features = _default_extract_features([float(index) for index in range(52)])

    assert list(features) == LABROOMS_DEPLOYMENT_FEATURES
    assert features["Bwd Packet Length Max"] == 5.0
    assert features["Bwd Packet Length Min"] == 5.0
    assert "Total Bwd Packets" not in features
    assert "HTTP Status Code" not in features


def test_packet_model_features_use_packet_length_slots():
    features = _default_extract_features(
        [float(index) for index in range(52)],
        feature_schema="packet-flow-v1",
    )

    assert list(features) == LABROOMS_DEPLOYMENT_FEATURES
    assert features["Bwd Packet Length Max"] == 10.0
    assert features["Bwd Packet Length Min"] == 11.0


def test_packet_syn_slot_is_not_treated_as_http_status():
    raw_features = [0.0] * 52
    raw_features[44] = 504.0

    assert ml_api._detect_schema_anomaly(raw_features, "packet-flow-v1") is None
    assert ml_api._detect_schema_anomaly(raw_features, "labrooms-app-layer-v2") == (
        "DoS",
        1,
        0.985,
    )


def test_packet_prediction_uses_model_without_http_override(monkeypatch):
    captured = {}

    class FakePreprocessor:
        def transform(self, frame):
            captured["frame"] = frame
            return frame

    class FakeModel:
        def predict(self, _features):
            return [2]

        def predict_proba(self, _features):
            return [[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]]

    monkeypatch.setattr(ml_api, "_champion_model", FakeModel())
    monkeypatch.setattr(ml_api, "_preprocessor", FakePreprocessor())
    monkeypatch.setattr(ml_api._drift_monitor, "process_batch", lambda rows: captured.update(records=rows))
    monkeypatch.setattr(ml_api._adapter, "observe", lambda _rows: None)
    monkeypatch.setattr(ml_api._adapter, "maybe_trigger", lambda: None)
    monkeypatch.setattr(ml_api._evaluator, "record", lambda _rows, _latency: None)

    features = [0.0] * 52
    features[10] = 100.0
    features[11] = 25.0
    features[44] = 504.0
    response = ml_api.app.test_client().post(
        "/predict",
        json={
            "flows": [{
                "flow_id": "packet-flow-test",
                "feature_schema": "packet-flow-v1",
                "features": features,
            }],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["predictions"][0]["label"] == "DDoS"
    assert captured["frame"]["Bwd Packet Length Max"].iloc[0] == 100.0
    assert captured["frame"]["Bwd Packet Length Min"].iloc[0] == 25.0
    record = captured["records"][0]
    assert record["feature_schema"] == "packet-flow-v1"
    assert record["ground_truth_label"] is None
    assert record["rule_override"] is False


def test_only_trusted_labels_are_buffered(tmp_path):
    adapter = _new_adapter(tmp_path)
    adapter.observe([
        _record(),  # high-confidence Normal prediction is not ground truth
        _record(ground_truth_label="Normal Traffic"),
        _record(
            flow_id="LBL::DoS::simulated-flow",
            label="Normal Traffic",
            label_index=0,
        ),
        _record(label="Brute Force", label_index=4, rule_override=True),
    ])

    status = adapter.get_status()
    assert status["online_learning_buffer"]["current_size"] == 3
    assert status["online_learning_buffer"]["label_sources"] == {
        "verified_label": 1,
        "rule_override": 1,
        "flow_id_tag": 1,
    }


def test_evaluator_rejects_model_only_labels():
    assert _resolve_pseudo_label(_record()) is None
    assert _resolve_pseudo_label(_record(ground_truth_label="Normal Traffic")) == 0
    assert _resolve_pseudo_label(_record(flow_id="LBL::DoS::flow")) == TARGET_CLASSES.index("DoS")
    assert _resolve_pseudo_label(
        _record(label="Web Attacks", label_index=5, rule_override=True)
    ) == TARGET_CLASSES.index("Web Attacks")


def test_drift_event_waits_for_labels_then_triggers_once(tmp_path):
    drift_event = {"detector": "ADWIN", "signal": "attack_ratio"}
    adapter = _new_adapter(
        tmp_path,
        events=[drift_event],
        min_buffer=2,
        min_attack=1,
    )
    started = []
    adapter._spawn_retrain = started.append

    adapter.maybe_trigger()
    waiting = adapter.get_status()
    assert waiting["last_event"]["type"] == "waiting"
    assert adapter._pending_drift_event == drift_event
    assert started == []

    recovered_adapter = _new_adapter(
        tmp_path,
        events=[],
        min_buffer=2,
        min_attack=1,
    )
    assert recovered_adapter._pending_drift_event == drift_event
    recovered_adapter._spawn_retrain = started.append
    recovered_adapter.observe([
        _record(flow_id="LBL::Normal_Traffic::normal"),
        _record(flow_id="LBL::DoS::attack", label="DoS", label_index=1),
    ])
    recovered_adapter.maybe_trigger()

    assert len(started) == 1
    assert "ADWIN drift alert" in started[0]
    assert recovered_adapter._pending_drift_event is None
