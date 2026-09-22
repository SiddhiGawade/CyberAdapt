/* ──────────────────────────────────────────────────────────────
   Dev Seed Script
   Creates a test company, auto-verifies domain, generates a
   sensor API key — ready to test the full pipeline locally.

   Usage:  node scripts/seed-dev.js
   ────────────────────────────────────────────────────────────── */
require('dotenv').config();
const mongoose = require('mongoose');
const crypto   = require('crypto');
const bcrypt   = require('bcryptjs');
const connectDB = require('../config/db');

const Company = require('../models/Company');
const ApiKey  = require('../models/ApiKey');

const TEST_COMPANY = {
  name:       'Acme Security Labs',
  domain:     'acme-test.local',
  adminEmail: 'admin@acme-test.local',
  password:   'Test@1234',
};

(async () => {
  await connectDB();
  console.log('\n🔧  CyberAdapt Dev Seed\n');

  /* ── 1. Upsert Company ── */
  let company = await Company.findOne({ domain: TEST_COMPANY.domain });

  if (!company) {
    const passwordHash = await bcrypt.hash(TEST_COMPANY.password, 12);
    const verificationToken = `cyberadapt-verify=${crypto.randomBytes(32).toString('hex')}`;

    company = await Company.create({
      name:              TEST_COMPANY.name,
      domain:            TEST_COMPANY.domain,
      adminEmail:        TEST_COMPANY.adminEmail,
      passwordHash,
      verificationToken,
      isVerified:        true,            // ← auto-verified for dev
      verifiedAt:        new Date(),
    });
    console.log('✅  Created & verified company:', company.domain);
  } else {
    // Ensure it's verified
    if (!company.isVerified) {
      company.isVerified = true;
      company.verifiedAt = new Date();
      await company.save();
      console.log('✅  Auto-verified existing company:', company.domain);
    } else {
      console.log('ℹ️   Company already exists:', company.domain);
    }
  }

  /* ── 2. Generate Sensor Key ── */
  const rawKey   = `ca_live_${crypto.randomBytes(32).toString('hex')}`;
  const keyHash  = crypto.createHash('sha256').update(rawKey).digest('hex');
  const keyPrefix = rawKey.substring(0, 8);

  await ApiKey.create({
    companyId: company._id,
    label:     'dev-test-sensor',
    keyHash,
    keyPrefix,
  });

  /* ── 3. Print Summary ── */
  console.log('\n' + '═'.repeat(60));
  console.log('  TEST CREDENTIALS');
  console.log('═'.repeat(60));
  console.log(`  Email    : ${TEST_COMPANY.adminEmail}`);
  console.log(`  Password : ${TEST_COMPANY.password}`);
  console.log(`  Domain   : ${TEST_COMPANY.domain} (auto-verified)`);
  console.log('═'.repeat(60));
  console.log('  SENSOR API KEY (use in mock sensor)');
  console.log('═'.repeat(60));
  console.log(`  ${rawKey}`);
  console.log('═'.repeat(60));
  console.log('\n🚀  You can now:');
  console.log('  1. Login at http://localhost:3000 with the above credentials');
  console.log('  2. Run the mock sensor:');
  console.log(`     python sensor/mock_sensor.py --key "${rawKey}" --url http://localhost:5000/api/telemetry/ingest`);
  console.log('  3. Watch flows appear in the Live Traffic dashboard\n');

  await mongoose.disconnect();
  process.exit(0);
})();
