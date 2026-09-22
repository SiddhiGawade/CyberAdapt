/* ──────────────────────────────────────────────────────────────
   Model: ApiKey
   Stores SHA-256 hashed sensor API keys.  The raw key is only
   ever returned once (at generation time).
   ────────────────────────────────────────────────────────────── */
const mongoose = require('mongoose');

const apiKeySchema = new mongoose.Schema({
  companyId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'Company',
    required: true,
    index: true,
  },
  label: {
    type: String,
    default: 'default',
    trim: true,
  },
  keyHash: {
    type: String,
    required: true,
    unique: true,
    index: true,
  },
  keyPrefix: {
    type: String,
    required: true,
  },
  isActive: {
    type: Boolean,
    default: true,
  },
  lastIngestAt: {
    type: Date,
    default: null,
  },
  createdAt: {
    type: Date,
    default: Date.now,
  },
});

module.exports = mongoose.model('ApiKey', apiKeySchema);
