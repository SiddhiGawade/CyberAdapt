const DEFAULT_TARGET_URL = 'http://127.0.0.1:5055';
const DEFAULT_ML_STATUS_URL = 'http://127.0.0.1:5001/concept-drift';
const MAX_REQUESTS = 5000;
const MAX_CONCURRENCY = 5;
const MAX_RATE_PER_SECOND = 10;
const MAX_DURATION_SECONDS = 60;
const REQUEST_TIMEOUT_MS = 4000;
const INFERENCE_WAIT_MS = 30000;

function parseArguments(args) {
  const options = {
    targetUrl: process.env.CYBERADAPT_TARGET_URL || DEFAULT_TARGET_URL,
    mlStatusUrl: process.env.CYBERADAPT_ML_STATUS_URL || DEFAULT_ML_STATUS_URL,
    requests: 200,
    concurrency: 4,
    rate: 5,
    durationSeconds: 60,
  };
  const flags = new Map([
    ['--target', 'targetUrl'],
    ['--requests', 'requests'],
    ['--concurrency', 'concurrency'],
    ['--rate', 'rate'],
    ['--duration-seconds', 'durationSeconds'],
  ]);

  for (let index = 0; index < args.length; index += 1) {
    const flag = args[index];
    if (flag === '--help') {
      console.log('Usage: node scripts/cyberadapt-local-load-test.js [--target URL] [--requests 1-5000] [--concurrency 1-5] [--rate 1-10] [--duration-seconds 1-60]');
      process.exit(0);
    }
    const optionName = flags.get(flag);
    if (!optionName || index + 1 >= args.length) {
      throw new Error(`Unknown or incomplete option: ${flag}`);
    }
    const value = args[index + 1];
    index += 1;
    if (optionName === 'targetUrl') {
      options.targetUrl = value;
      continue;
    }
    if (!/^\d+$/.test(value)) {
      throw new Error(`${flag} must be a positive integer.`);
    }
    options[optionName] = Number(value);
  }

  for (const [name, value, maximum] of [
    ['requests', options.requests, MAX_REQUESTS],
    ['concurrency', options.concurrency, MAX_CONCURRENCY],
    ['rate', options.rate, MAX_RATE_PER_SECOND],
    ['duration-seconds', options.durationSeconds, MAX_DURATION_SECONDS],
  ]) {
    if (!Number.isInteger(value) || value < 1 || value > maximum) {
      throw new Error(`${name} must be an integer from 1 to ${maximum}.`);
    }
  }
  validateTarget(options.targetUrl);
  return options;
}

function validateTarget(value) {
  let target;
  try {
    target = new URL(value);
  } catch {
    throw new Error('Target must be a valid local HTTP URL.');
  }
  const approved = target.protocol === 'http:'
    && !target.username
    && !target.password
    && !target.search
    && !target.hash
    && target.pathname === '/'
    && (
      (['127.0.0.1', 'localhost'].includes(target.hostname) && target.port === '5055')
      || (target.hostname === 'target' && target.port === '3000')
    );
  if (!approved) {
    throw new Error('Refusing to send load traffic. Target must be http://127.0.0.1:5055 or the Compose-only http://target:3000.');
  }
}

async function readDriftStatus(url) {
  let response;
  try {
    response = await fetch(url, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    throw new Error(`Could not reach CyberAdapt drift API at ${url}: ${error.message}`);
  }
  if (!response.ok) {
    throw new Error(`CyberAdapt drift API returned HTTP ${response.status}.`);
  }
  const status = await response.json();
  if (!Number.isInteger(status.samples_processed)) {
    throw new Error('CyberAdapt drift API response has no valid samples_processed count.');
  }
  return status;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  const target = new URL(options.targetUrl);
  const before = await readDriftStatus(options.mlStatusUrl);
  let targetResponse;
  try {
    targetResponse = await fetch(target, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  } catch (error) {
    throw new Error(`Local target health request failed: ${error.message}`);
  }
  if (!targetResponse.ok) {
    throw new Error(`Local target returned HTTP ${targetResponse.status} before the test.`);
  }

  console.log('Starting bounded, single-machine HTTP load test (not DDoS).');
  console.log(`Target: ${target.origin}; requests: ${options.requests}; concurrency: ${options.concurrency}; maximum rate: ${options.rate}/second; time limit: ${options.durationSeconds}s.`);
  console.log('Requests are plain GETs to the local homepage. No exploit payloads or attack labels are sent.');
  console.log(`Before: ${before.samples_processed} model samples; predicted attack ratio ${before.predicted_attack_ratio_recent ?? 'unknown'}; drift ${before.drift_state ?? 'unknown'}.`);

  const startedAt = Date.now();
  const deadline = startedAt + options.durationSeconds * 1000;
  const intervalMs = 1000 / options.rate;
  let nextRequestAt = startedAt;
  let requestsStarted = 0;
  let nonSuccessResponses = 0;
  let requestErrors = 0;
  const statusCounts = new Map();

  async function takeRateSlot() {
    const now = Date.now();
    const scheduledAt = Math.max(now, nextRequestAt);
    if (scheduledAt >= deadline) return false;
    nextRequestAt = scheduledAt + intervalMs;
    const waitMs = scheduledAt - now;
    if (waitMs > 0) await sleep(waitMs);
    return Date.now() < deadline;
  }

  async function worker() {
    while (requestsStarted < options.requests && Date.now() < deadline) {
      if (!(await takeRateSlot())) return;
      if (requestsStarted >= options.requests) return;
      requestsStarted += 1;
      try {
        const response = await fetch(target, {
          method: 'GET',
          signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
        });
        const status = response.status;
        statusCounts.set(status, (statusCounts.get(status) || 0) + 1);
        if (!response.ok) nonSuccessResponses += 1;
        await response.body?.cancel();
      } catch (error) {
        requestErrors += 1;
        console.error(`[load test] Request ${requestsStarted} failed: ${error.message}`);
      }
    }
  }

  await Promise.all(Array.from({ length: options.concurrency }, () => worker()));
  const elapsedSeconds = (Date.now() - startedAt) / 1000;
  const sentText = [...statusCounts.entries()]
    .sort(([left], [right]) => left - right)
    .map(([status, count]) => `${status}: ${count}`)
    .join(', ') || 'none';
  console.log(`Finished: ${requestsStarted} request(s) in ${elapsedSeconds.toFixed(1)}s; HTTP statuses: ${sentText}; errors: ${requestErrors}.`);

  const inferenceDeadline = Date.now() + INFERENCE_WAIT_MS;
  let after = await readDriftStatus(options.mlStatusUrl);
  while (after.samples_processed <= before.samples_processed && Date.now() < inferenceDeadline) {
    await sleep(2000);
    after = await readDriftStatus(options.mlStatusUrl);
  }
  console.log(`CyberAdapt samples: ${before.samples_processed} -> ${after.samples_processed}.`);
  console.log(`Predicted attack ratio: ${before.predicted_attack_ratio_recent ?? 'unknown'} -> ${after.predicted_attack_ratio_recent ?? 'unknown'}; drift: ${after.drift_state ?? 'unknown'}.`);
  console.log('Traffic count is a test condition, not an attack label. A model prediction or drift alert is not guaranteed.');

  if (after.samples_processed <= before.samples_processed) {
    throw new Error('No newly captured flows reached model inference within 30 seconds. Check the sensor and backend logs.');
  }
  if (requestErrors > 0 || nonSuccessResponses > 0) {
    throw new Error(`Load test completed with ${requestErrors} request error(s) and ${nonSuccessResponses} non-2xx response(s).`);
  }
}

main().catch((error) => {
  console.error(`[CyberAdapt local load test] ${error.message}`);
  process.exitCode = 1;
});
