/* ──────────────────────────────────────────────────────────────
   Routes: /api/telemetry
   Sensor data ingestion & recent-flow retrieval for dashboard.
   ────────────────────────────────────────────────────────────── */
const express = require('express');
const router  = express.Router();

const TelemetryLog      = require('../models/TelemetryLog');
const ApiKey            = require('../models/ApiKey');
const authenticateSensor = require('../middleware/authenticateSensor');
const auth               = require('../middleware/auth');

/* ─────────────── FEATURE SCHEMA CONSTANTS ─────────────────── */
const FEATURE_COUNT   = 52;
const FLOW_DURATION_IDX = 1;   // index of flow-duration in the 52-feature vector

/* ───────────────────────── INGEST ───────────────────────────── */
router.post('/ingest', authenticateSensor, async (req, res, next) => {
  try {
    const { sensor_id, batch_timestamp, flow_count, flows } = req.body;

    /* ── Basic envelope validation ── */
    if (!sensor_id || batch_timestamp == null || !Array.isArray(flows)) {
      return res.status(400).json({ error: 'Invalid payload: sensor_id, batch_timestamp, and flows[] required' });
    }

    const valid   = [];
    const errors  = [];

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
        batchTimestamp:  batch_timestamp,
        flowId:         f.flow_id,
        features,
      });
    }

    if (valid.length === 0) {
      return res.status(422).json({
        error: 'All flow records were malformed',
        details: errors,
      });
    }

    /* Bulk insert valid records */
    await TelemetryLog.insertMany(valid, { ordered: false });

    /* Touch lastIngestAt on the API key */
    await ApiKey.findByIdAndUpdate(req.apiKeyId, { lastIngestAt: new Date() });

    return res.status(202).json({
      accepted: valid.length,
      rejected: errors.length,
      errors: errors.length > 0 ? errors : undefined,
    });
  } catch (err) {
    next(err);
  }
});

/* ────────────────── RECENT FLOWS (Dashboard) ────────────────── */
router.get('/recent-flows', auth, async (req, res, next) => {
  try {
    const flows = await TelemetryLog.find({ companyId: req.user.id })
      .sort({ receivedAt: -1 })
      .limit(20)
      .lean();

    return res.json({ flows });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
