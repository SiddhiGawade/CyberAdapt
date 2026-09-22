/* ──────────────────────────────────────────────────────────────
   Routes: /api/auth
   Registration, Login, DNS Verification, API Key Management
   ────────────────────────────────────────────────────────────── */
const express  = require('express');
const crypto   = require('crypto');
const bcrypt   = require('bcryptjs');
const jwt      = require('jsonwebtoken');
const dns      = require('dns').promises;
const router   = express.Router();

const Company = require('../models/Company');
const ApiKey  = require('../models/ApiKey');
const auth    = require('../middleware/auth');

/* ────────────────────────── REGISTER ────────────────────────── */
router.post('/register', async (req, res, next) => {
  try {
    const { name, domain, adminEmail, password } = req.body;

    if (!name || !domain || !adminEmail || !password) {
      return res.status(400).json({ error: 'All fields are required (name, domain, adminEmail, password)' });
    }

    /* Check for existing company/email */
    const existing = await Company.findOne({
      $or: [{ domain: domain.toLowerCase() }, { adminEmail: adminEmail.toLowerCase() }],
    });
    if (existing) {
      return res.status(409).json({ error: 'Domain or email already registered' });
    }

    const passwordHash = await bcrypt.hash(password, 12);
    const verificationToken = `cyberadapt-verify=${crypto.randomBytes(32).toString('hex')}`;

    const company = await Company.create({
      name,
      domain: domain.toLowerCase(),
      adminEmail: adminEmail.toLowerCase(),
      passwordHash,
      verificationToken,
    });

    return res.status(201).json({
      message: 'Company registered. Add the verification TXT record to your domain DNS.',
      companyId: company._id,
      domain: company.domain,
      verificationToken: company.verificationToken,
    });
  } catch (err) {
    next(err);
  }
});

/* ─────────────────────────── LOGIN ──────────────────────────── */
router.post('/login', async (req, res, next) => {
  try {
    const { email, password } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    const company = await Company.findOne({ adminEmail: email.toLowerCase() });
    if (!company) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const valid = await bcrypt.compare(password, company.passwordHash);
    if (!valid) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const token = jwt.sign(
      { id: company._id, domain: company.domain },
      process.env.JWT_SECRET,
      { expiresIn: process.env.JWT_EXPIRES_IN || '24h' },
    );

    return res.json({
      token,
      company: {
        id: company._id,
        name: company.name,
        domain: company.domain,
        isVerified: company.isVerified,
        verificationToken: company.verificationToken,
      },
    });
  } catch (err) {
    next(err);
  }
});

/* ────────────────────── DNS VERIFICATION ────────────────────── */
router.post('/verify-dns', auth, async (req, res, next) => {
  try {
    const company = await Company.findById(req.user.id);
    if (!company) return res.status(404).json({ error: 'Company not found' });

    if (company.isVerified) {
      return res.json({ verified: true, message: 'Domain already verified' });
    }

    let txtRecords;
    try {
      txtRecords = await dns.resolveTxt(company.domain);
    } catch (dnsErr) {
      return res.status(400).json({
        verified: false,
        error: `DNS lookup failed for ${company.domain}: ${dnsErr.code || dnsErr.message}`,
      });
    }

    /* dns.resolveTxt returns [[chunk1, chunk2], …].  Flatten & check. */
    const flat = txtRecords.map((r) => r.join('')).flat();
    const found = flat.some((entry) => entry.trim() === company.verificationToken);

    if (!found) {
      return res.status(400).json({
        verified: false,
        error: 'Verification token not found in DNS TXT records. It may take time to propagate.',
      });
    }

    company.isVerified = true;
    company.verifiedAt = new Date();
    await company.save();

    return res.json({ verified: true, message: 'Domain verified successfully' });
  } catch (err) {
    next(err);
  }
});

/* ────────────────── GENERATE SENSOR API KEY ─────────────────── */
router.post('/generate-key', auth, async (req, res, next) => {
  try {
    const company = await Company.findById(req.user.id);
    if (!company) return res.status(404).json({ error: 'Company not found' });

    if (!company.isVerified) {
      return res.status(403).json({ error: 'Domain must be verified before generating sensor keys' });
    }

    const { label } = req.body;
    const rawKey   = `ca_live_${crypto.randomBytes(32).toString('hex')}`;
    const keyHash  = crypto.createHash('sha256').update(rawKey).digest('hex');
    const keyPrefix = rawKey.substring(0, 8);

    await ApiKey.create({
      companyId: company._id,
      label: label || 'default',
      keyHash,
      keyPrefix,
    });

    return res.status(201).json({
      message: 'Sensor key generated. Store it securely — it will not be shown again.',
      key: rawKey,
      keyPrefix,
    });
  } catch (err) {
    next(err);
  }
});

/* ─────────────────────── LIST API KEYS ──────────────────────── */
router.get('/keys', auth, async (req, res, next) => {
  try {
    const keys = await ApiKey.find({ companyId: req.user.id })
      .select('keyPrefix label isActive lastIngestAt createdAt')
      .sort({ createdAt: -1 });

    return res.json({ keys });
  } catch (err) {
    next(err);
  }
});

/* ──────────────── GET CURRENT USER / COMPANY ────────────────── */
router.get('/me', auth, async (req, res, next) => {
  try {
    const company = await Company.findById(req.user.id).select('-passwordHash');
    if (!company) return res.status(404).json({ error: 'Company not found' });
    return res.json({ company });
  } catch (err) {
    next(err);
  }
});

module.exports = router;
