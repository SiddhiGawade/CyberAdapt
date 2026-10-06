const express = require('express');

const HOST = process.env.HOST || '127.0.0.1';
const PORT = Number(process.env.PORT || 5055);
const TEST_CASES = {
  normal: { status: 200, message: 'Safe test response' },
  'dos-signal': { status: 504, message: 'Synthetic timeout signal' },
  'auth-denied': { status: 401, message: 'Synthetic auth rejection' },
  'server-error': { status: 500, message: 'Synthetic server error' },
};

function main() {
  const app = express();
  app.use(express.json({ limit: '1kb' }));

  app.get('/health', (_req, res) => res.json({ status: 'ready', host: HOST, port: PORT }));
  app.post('/test/:scenario', (req, res) => {
    const testCase = TEST_CASES[req.params.scenario];
    if (!testCase) return res.status(404).json({ error: 'Unknown safe test scenario' });
    if (req.params.scenario === 'auth-denied') {
      if (
        typeof req.body?.username !== 'string'
        || typeof req.body?.password !== 'string'
      ) {
        return res.status(400).json({ error: 'Test username and password are required' });
      }
      console.log(`[test target] Rejected test login for ${req.body.username}`);
      return res.status(401).json({ message: 'Invalid test credentials' });
    }
    console.log(`[test target] ${req.method} ${req.path} -> ${testCase.status}`);
    return res.status(testCase.status).json({ message: testCase.message });
  });

  app.listen(PORT, HOST, () => {
    console.log(`[test target] Listening only on http://${HOST}:${PORT}`);
    console.log(`[test target] Scenarios: ${Object.keys(TEST_CASES).join(', ')}`);
    console.log('[test target] Packet capture must run separately on the loopback adapter.');
    console.log('[test target] Safe local traffic fixture; it does not run exploits.');
  });
}

main();
