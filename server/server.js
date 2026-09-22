/* ──────────────────────────────────────────────────────────────
   CyberAdapt API Server — Entry Point
   ────────────────────────────────────────────────────────────── */
require('dotenv').config();
const express = require('express');
const cors    = require('cors');
const connectDB = require('./config/db');

const authRoutes      = require('./routes/auth');
const telemetryRoutes = require('./routes/telemetry');

const app  = express();
const PORT = process.env.PORT || 5000;

/* ── Global Middleware ── */
app.use(cors());
app.use(express.json({ limit: '5mb' }));   // sensor batches can be sizeable

/* ── Health Check ── */
app.get('/api/health', (_req, res) => {
  res.json({ status: 'operational', ts: Date.now() });
});

/* ── Route Mounts ── */
app.use('/api/auth',      authRoutes);
app.use('/api/telemetry', telemetryRoutes);

/* ── Centralised Error Handler ── */
app.use((err, _req, res, _next) => {
  console.error('[SERVER ERROR]', err);
  res.status(err.status || 500).json({ error: err.message || 'Internal Server Error' });
});

/* ── Boot ── */
(async () => {
  await connectDB();
  app.listen(PORT, () => {
    console.log(`\n⚡  CyberAdapt API listening on port ${PORT}\n`);
  });
})();
