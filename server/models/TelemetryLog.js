/* ──────────────────────────────────────────────────────────────
   Model: TelemetryLog
   Each document represents a single network flow record
   ingested from an edge sensor (52-feature vector).
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
  features: {
    type: [Number],
    validate: {
      validator: (arr) => arr.length === 52,
      message: 'features must contain exactly 52 numeric values',
    },
  },
  receivedAt: {
    type: Date,
    default: Date.now,
  },
});

/* Compound index for fast recent-flow queries per company */
telemetryLogSchema.index({ companyId: 1, receivedAt: -1 });

module.exports = mongoose.model('TelemetryLog', telemetryLogSchema);
