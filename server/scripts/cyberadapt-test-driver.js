const BASE_URL = process.env.CYBERADAPT_TARGET_URL || 'http://127.0.0.1:5055';
const INTERVAL_MS = 250;
const ATTACK_CASES = ['dos-signal', 'auth-denied', 'server-error'];

function parseCount(args, option, fallback, maximum) {
  const index = args.indexOf(option);
  if (index === -1) return fallback;
  const value = Number(args[index + 1]);
  if (!Number.isInteger(value) || value < 0 || value > maximum) {
    throw new Error(`${option} must be an integer from 0 to ${maximum}.`);
  }
  return value;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function sendScenario(scenario, expectedStatus, attemptIndex) {
  const body = scenario === 'auth-denied'
    ? { username: 'cyberadapt-lab-user', password: `invalid-${attemptIndex}` }
    : { fixture: 'CyberAdapt safe local test' };
  const response = await fetch(`${BASE_URL}/test/${scenario}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status !== expectedStatus) {
    const body = await response.text();
    throw new Error(`${scenario} returned HTTP ${response.status}, expected ${expectedStatus}: ${body}`);
  }
}

async function main() {
  const args = process.argv.slice(2);
  const normalCount = parseCount(args, '--normal-count', 10, 1000);
  const attackCount = parseCount(args, '--attack-count', 5, 250);

  const health = await fetch(`${BASE_URL}/health`);
  if (!health.ok) {
    throw new Error(`Test target health check failed with HTTP ${health.status}.`);
  }

  let sent = 0;
  console.log(`Sending ${normalCount} normal and ${attackCount} of each safe attack-signal scenario.`);
  console.log(`Rate is limited to one request every ${INTERVAL_MS} ms; destination is ${BASE_URL}.`);

  for (const [scenario, count, expectedStatus] of [
    ['normal', normalCount, 200],
    ...ATTACK_CASES.map((name) => [name, attackCount, name === 'dos-signal' ? 504 : name === 'auth-denied' ? 401 : 500]),
  ]) {
    for (let index = 0; index < count; index += 1) {
      await sendScenario(scenario, expectedStatus, index);
      sent += 1;
      if (sent % 25 === 0) console.log(`Sent ${sent} local test requests.`);
      await sleep(INTERVAL_MS);
    }
    console.log(`Completed ${scenario}: ${count} request(s).`);
  }

  console.log(`Finished: ${sent} requests sent to the local server.`);
}

main().catch((error) => {
  console.error(`[test driver] ${error.message}`);
  process.exitCode = 1;
});
