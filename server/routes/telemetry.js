/* ──────────────────────────────────────────────────────────────
   Routes: /api/telemetry
   Sensor data ingestion & recent-flow retrieval for dashboard.
   ────────────────────────────────────────────────────────────── */
const express = require('express');
const router  = express.Router();

const TelemetryLog       = require('../models/TelemetryLog');
const ApiKey             = require('../models/ApiKey');
const authenticateSensor = require('../middleware/authenticateSensor');
const auth               = require('../middleware/auth');

/* ─────────────── FEATURE SCHEMA CONSTANTS ─────────────────── */
const FEATURE_COUNT     = 52;
const FLOW_DURATION_IDX = 1;   // index of flow-duration in the 52-feature vector
const FEATURE_SCHEMAS   = new Set(['labrooms-app-layer-v2', 'packet-flow-v1']);
const TARGET_CLASSES    = new Set([
  'Normal Traffic',
  'DoS',
  'DDoS',
  'Port Scanning',
  'Brute Force',
  'Web Attacks',
  'Bots',
]);

/* ── ML Inference microservice URL (set ML_API_URL in .env) ── */
const ML_API_URL = (process.env.ML_API_URL || 'http://127.0.0.1:5001').replace(/\/$/, '');

/**
 * Fire-and-forget: forward a batch of validated flows to the Python ML API,
 * then back-fill the returned threat labels onto the stored TelemetryLog docs.
 *
 * Runs asynchronously after the HTTP 202 response has already been sent so
 * sensor latency is never impacted by ML inference time.
 */
async function classifyAndAnnotate(flowDocs) {
  try {
    const payload = {
      flows: flowDocs.map((doc) => ({
        flow_id: doc.flowId,
        features: doc.features,
        feature_schema: doc.featureSchema,
        ...(doc.groundTruthLabel ? { ground_truth_label: doc.groundTruthLabel } : {}),
      })),
    };

    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 5000); // 5-second timeout

    const resp = await fetch(`${ML_API_URL}/predict`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
      signal:  ctrl.signal,
    });
    clearTimeout(timeout);

    if (!resp.ok) return;

    const { predictions } = await resp.json();
    if (!Array.isArray(predictions)) return;

    // Build a flowId → prediction map
    const predMap = {};
    for (const p of predictions) {
      predMap[p.flow_id] = { label: p.label, confidence: p.confidence };
    }

    // Bulk-update TelemetryLog documents with threat labels
    const bulkOps = flowDocs
      .filter((doc) => predMap[doc.flowId])
      .map((doc) => ({
        updateOne: {
          filter: { _id: doc._id },
          update: {
            $set: {
              threatLabel:      predMap[doc.flowId].label,
              threatConfidence: predMap[doc.flowId].confidence,
            },
          },
        },
      }));

    if (bulkOps.length > 0) {
      await TelemetryLog.bulkWrite(bulkOps, { ordered: false });
    }

  } catch (err) {
    // Non-fatal: ML annotation failure must never crash the ingestion path
    if (err.name !== 'AbortError') {
      console.warn('[ML classify] annotation skipped:', err.message);
    }
  }
}

/* ───────────────────────── INGEST ───────────────────────────── */
router.post('/ingest', authenticateSensor, async (req, res, next) => {
  try {
    const { sensor_id, batch_timestamp, flow_count, flows } = req.body;

    /* ── Basic envelope validation ── */
    if (!sensor_id || batch_timestamp == null || !Array.isArray(flows)) {
      return res.status(400).json({ error: 'Invalid payload: sensor_id, batch_timestamp, and flows[] required' });
    }

    const valid  = [];
    const errors = [];

    for (let i = 0; i < flows.length; i++) {
      const f = flows[i];

      /* Each flow must have a flow_id and a 52-number feature array */
      if (!f || !f.flow_id || !Array.isArray(f.features)) {
        errors.push({ index: i, reason: 'Missing flow_id or features array' });
        continue;
      }

      if (f.features.length !== FEATURE_COUNT) {
        errors.push({ index: i, reason: `Expected ${FEATURE_COUNT} features, got ${f.features.length}` });
        continue;
      }

      const featureSchema = f.feature_schema || 'labrooms-app-layer-v2';
      if (typeof featureSchema !== 'string' || !FEATURE_SCHEMAS.has(featureSchema)) {
        errors.push({ index: i, reason: 'feature_schema must be a supported sensor schema' });
        continue;
      }

      if (
        f.ground_truth_label != null
        && (typeof f.ground_truth_label !== 'string' || !TARGET_CLASSES.has(f.ground_truth_label))
      ) {
        errors.push({ index: i, reason: 'ground_truth_label must be a supported verified class label' });
        continue;
      }

      const allNumbers = f.features.every((v) => typeof v === 'number' && !Number.isNaN(v));
      if (!allNumbers) {
        errors.push({ index: i, reason: 'All features must be finite numbers' });
        continue;
      }

      /* Clamp negative flow duration (index 1) to 0 */
      const features = [...f.features];
      if (features[FLOW_DURATION_IDX] < 0) {
        features[FLOW_DURATION_IDX] = 0;
      }

      valid.push({
        companyId:      req.companyId,
        sensorId:       sensor_id,
        batchTimestamp: batch_timestamp,
        flowId:         f.flow_id,
        featureSchema,
        features,
        groundTruthLabel: f.ground_truth_label || null,
      });
    }

    if (valid.length === 0) {
      return res.status(422).json({
        error:   'All flow records were malformed',
        details: errors,
      });
    }

    /* Bulk insert valid records */
    const inserted = await TelemetryLog.insertMany(valid, { ordered: false });

    /* Touch lastIngestAt on the API key */
    await ApiKey.findByIdAndUpdate(req.apiKeyId, { lastIngestAt: new Date() });

    /* Respond immediately — then classify in the background */
    res.status(202).json({
      accepted: valid.length,
      rejected: errors.length,
      errors:   errors.length > 0 ? errors : undefined,
    });

    /* Fire-and-forget ML classification (does NOT await) */
    classifyAndAnnotate(inserted).catch(() => {});


  } catch (err) {
    next(err);
  }
});

/* ────────────────── RECENT FLOWS (Dashboard) ────────────────── */
router.get('/recent-flows', auth, async (req, res, next) => {
  try {
    const flows = await TelemetryLog.find({ companyId: req.user.id })
      .sort({ receivedAt: -1 })
      .limit(100)
      .lean();

    return res.json({ flows });
  } catch (err) {
    next(err);
  }
});

/* ──────────────── ML INFERENCE PROXY (Dashboard) ────────────── */
/* GET /api/telemetry/ml-health — relay liveness from the Python API */
router.get('/ml-health', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/health`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ status: 'unreachable', error: err.message });
  }
});

/* GET /api/telemetry/model-info — relay model metadata from the Python API */
router.get('/model-info', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/model-info`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* GET /api/telemetry/concept-drift */
router.get('/concept-drift', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/concept-drift`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* GET /api/telemetry/adaptation */
router.get('/adaptation', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/adaptation`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* GET /api/telemetry/explain */
router.get('/explain', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/explain`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* GET /api/telemetry/evaluation */
router.get('/evaluation', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 3000);
    const resp    = await fetch(`${ML_API_URL}/evaluation`, { signal: ctrl.signal });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.ok ? 200 : 503).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* ──────────────── ML ACTION PROXIES (Dashboard) ─────────────── */
/* POST /api/telemetry/adaptation/trigger — manual retrain trigger.
   Status passthrough: UI distinguishes 202 accepted / 409 busy / 422. */
router.post('/adaptation/trigger', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 5000);
    const resp    = await fetch(`${ML_API_URL}/adaptation/trigger`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      signal:  ctrl.signal,
    });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.status).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

/* POST /api/telemetry/admin/reset — demo reset (Flask enforces DEMO_MODE=1).
   Status passthrough: UI distinguishes 200 reset / 403 forbidden. */
router.post('/admin/reset', auth, async (req, res, next) => {
  try {
    const ctrl    = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 5000);
    const resp    = await fetch(`${ML_API_URL}/admin/reset`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      signal:  ctrl.signal,
    });
    clearTimeout(timeout);
    const data    = await resp.json();
    return res.status(resp.status).json(data);
  } catch (err) {
    return res.status(503).json({ error: err.message });
  }
});

module.exports = router;
