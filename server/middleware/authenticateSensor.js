/* ──────────────────────────────────────────────────────────────
   Middleware: Sensor API-Key Authentication
   Extracts X-Sensor-Key header, SHA-256 hashes it, looks up
   the active ApiKey record, and attaches req.companyId.
   ────────────────────────────────────────────────────────────── */
const crypto = require('crypto');
const ApiKey = require('../models/ApiKey');

async function authenticateSensor(req, res, next) {
  const rawKey = req.headers['x-sensor-key'];

  if (!rawKey) {
    return res.status(401).json({ error: 'Missing X-Sensor-Key header' });
  }

  const keyHash = crypto.createHash('sha256').update(rawKey).digest('hex');

  try {
    const apiKey = await ApiKey.findOne({ keyHash, isActive: true });
    if (!apiKey) {
      return res.status(403).json({ error: 'Invalid or revoked sensor key' });
    }

    req.companyId = apiKey.companyId;
    req.apiKeyId  = apiKey._id;
    next();
  } catch (err) {
    console.error('[SENSOR AUTH]', err);
    return res.status(500).json({ error: 'Sensor authentication failed' });
  }
}

module.exports = authenticateSensor;
