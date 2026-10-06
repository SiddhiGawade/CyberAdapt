/* ──────────────────────────────────────────────────────────────
   Model: TelemetryLog
   Each document represents a single network flow record
   ingested from an edge sensor (52-feature vector).
   Threat classification labels are back-filled asynchronously
   by the Python ML inference microservice after ingest.
   ────────────────────────────────────────────────────────────── */
const mongoose = require('mongoose');

const telemetryLogSchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true,
  },
  sensorId: {
    type: String,
    required: true,
  },
  batchTimestamp: {
    type: Number,
    required: true,
  },
  flowId: {
    type: String,
    required: true,
  },
  featureSchema: {
    type: String,
    enum: ['labrooms-app-layer-v2', 'packet-flow-v1'],
    default: 'labrooms-app-layer-v2',
  },
  features: {
    type: [Number],
    validate: {
      validator: (arr) => arr.length === 52,
      message: 'features must contain exactly 52 numeric values',
    },
  },
  /* Optional independently verified label supplied by a trusted sensor. */
  groundTruthLabel: {
    type: String,
    default: null,
    enum: [
      null,
      'Normal Traffic',
      'DoS',
      'DDoS',
      'Port Scanning',
      'Brute Force',
      'Web Attacks',
      'Bots',
    ],
  },
  /* ── ML Threat Classification (populated after ML inference) ── */
  threatLabel: {
    type: String,
    default: null,
    enum: [
      null,
      'Normal Traffic',
      'DoS',
      'DDoS',
      'Port Scanning',
      'Brute Force',
      'Web Attacks',
      'Bots',
    ],
  },
  threatConfidence: {
    type: Number,   // 0.0 – 1.0 probability score from the model
    default: null,
  },
  receivedAt: {
    type: Date,
    default: Date.now,
  },
});

/* Compound index for fast recent-flow queries per company */
telemetryLogSchema.index({ companyId: 1, receivedAt: -1 });

/* Index to efficiently retrieve all threat flows for a company */
telemetryLogSchema.index({ companyId: 1, threatLabel: 1, receivedAt: -1 });

module.exports = mongoose.model('TelemetryLog', telemetryLogSchema);
