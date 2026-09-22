/* ──────────────────────────────────────────────────────────────
   Page: Sensor Setup — 3-Step Provisioning Flow
   Step 1: DNS Domain Verification
   Step 2: API Key Generation (locked until verified)
   Step 3: Sensor Deployment (download + Docker command)
   ────────────────────────────────────────────────────────────── */
import { useState, useEffect } from 'react';
import {
  Globe, CheckCircle2, XCircle, Loader2, Key, Copy, Check, Download,
  Terminal, AlertTriangle, Shield, Lock, Eye, EyeOff, ChevronRight,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import GlowCard from '../components/GlowCard';
import api from '../api';

/* ─────────────────── Step Indicator ─────────────────── */
function StepHeader({ step, title, subtitle, active, completed }) {
  return (
    <div className="flex items-center gap-4 mb-5">
      <div
        className={`w-10 h-10 rounded-xl flex items-center justify-center font-mono font-bold text-sm border transition-all duration-500
          ${completed
            ? 'bg-cyber-green/10 border-cyber-green/40 text-cyber-green shadow-glow-green'
            : active
              ? 'bg-cyber-cyan/10 border-cyber-cyan/40 text-cyber-cyan shadow-glow-cyan animate-glow'
              : 'bg-cyber-card2 border-cyber-border text-cyber-dim'
          }`}
      >
        {completed ? <CheckCircle2 className="w-5 h-5" /> : step}
      </div>
      <div>
        <h3 className={`text-sm font-bold tracking-wider uppercase ${active || completed ? 'text-white' : 'text-cyber-dim'}`}>
          {title}
        </h3>
        <p className="text-xs text-cyber-dim mt-0.5">{subtitle}</p>
      </div>
    </div>
  );
}

/* ─────────────────── Key Modal ─────────────────── */
function KeyModal({ rawKey, onClose }) {
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(false);

  async function copyKey() {
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in">
      <div className="bg-cyber-card border border-cyber-cyan/30 rounded-2xl shadow-glow-cyan max-w-lg w-full mx-4 p-6 space-y-5 animate-slide-in">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyber-amber/10 border border-cyber-amber/30">
            <AlertTriangle className="w-5 h-5 text-cyber-amber" />
          </div>
          <div>
            <h3 className="text-base font-bold text-white">Sensor Key Generated</h3>
            <p className="text-xs text-cyber-amber">This key will only be shown once. Store it securely.</p>
          </div>
        </div>

        {/* Key display */}
        <div className="relative bg-cyber-bg rounded-lg border border-cyber-border p-4">
          <code className="text-sm font-mono text-cyber-green break-all select-all leading-relaxed">
            {visible ? rawKey : rawKey.substring(0, 12) + '•'.repeat(40)}
          </code>
          <div className="absolute top-2 right-2 flex gap-1">
            <button
              onClick={() => setVisible(!visible)}
              className="p-1.5 rounded-md bg-cyber-card hover:bg-cyber-card2 transition-colors"
              title={visible ? 'Hide' : 'Reveal'}
            >
              {visible
                ? <EyeOff className="w-3.5 h-3.5 text-cyber-dim" />
                : <Eye    className="w-3.5 h-3.5 text-cyber-dim" />}
            </button>
            <button
              onClick={copyKey}
              className="p-1.5 rounded-md bg-cyber-card hover:bg-cyber-card2 transition-colors"
              title="Copy"
            >
              {copied
                ? <Check className="w-3.5 h-3.5 text-cyber-green" />
                : <Copy  className="w-3.5 h-3.5 text-cyber-dim" />}
            </button>
          </div>
        </div>

        {/* Security warning */}
        <div className="flex items-start gap-2 px-4 py-3 bg-cyber-red/5 border border-cyber-red/15 rounded-lg">
          <Lock className="w-4 h-4 text-cyber-red shrink-0 mt-0.5" />
          <p className="text-xs text-cyber-text leading-relaxed">
            <strong className="text-cyber-red">Security Warning:</strong> This key grants sensor ingestion access to your organisation.
            Never commit it to version control or expose it in client-side code. Use environment variables or a secrets manager.
          </p>
        </div>

        <button onClick={onClose} className="btn-cyber w-full">
          I've Stored the Key Securely
        </button>
      </div>
    </div>
  );
}

/* ─────────────────── MAIN COMPONENT ─────────────────── */
export default function SensorSetup() {
  const { user, refreshUser } = useAuth();

  /* DNS verification */
  const [verifying, setVerifying]   = useState(false);
  const [dnsResult, setDnsResult]   = useState(null);     // { ok, msg }

  /* Key generation */
  const [keyLabel, setKeyLabel]     = useState('');
  const [generating, setGenerating] = useState(false);
  const [rawKey, setRawKey]         = useState(null);      // triggers modal
  const [keys, setKeys]             = useState([]);

  /* Copy helpers */
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedCmd, setCopiedCmd]     = useState(false);

  const isVerified = user?.isVerified;

  /* Load existing keys */
  useEffect(() => {
    api.get('/auth/keys').then((d) => setKeys(d.keys || [])).catch(() => {});
  }, [rawKey]);

  /* ── DNS Verify ── */
  async function handleVerify() {
    setVerifying(true);
    setDnsResult(null);
    try {
      const data = await api.post('/auth/verify-dns');
      setDnsResult({ ok: true, msg: data.message });
      await refreshUser();
    } catch (err) {
      setDnsResult({ ok: false, msg: err.data?.error || err.message });
    } finally {
      setVerifying(false);
    }
  }

  /* ── Generate Key ── */
  async function handleGenerateKey() {
    setGenerating(true);
    try {
      const data = await api.post('/auth/generate-key', { label: keyLabel || 'default' });
      setRawKey(data.key);
      setKeyLabel('');
    } catch (err) {
      alert(err.message);
    } finally {
      setGenerating(false);
    }
  }

  /* ── Copy helpers ── */
  function copyToClipboard(text, setter) {
    navigator.clipboard.writeText(text);
    setter(true);
    setTimeout(() => setter(false), 2000);
  }

  const dockerCmd = `docker run -d --net=host \\
  -e SENSOR_KEY="ca_live_..." \\
  -e INGEST_URL="https://api.cyberadapt.io/api/telemetry/ingest" \\
  cyberadapt-sensor`;

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold tracking-[0.15em] text-white uppercase">Sensor Setup</h1>
        <p className="text-sm text-cyber-text mt-1">
          Configure and deploy edge sensors for <span className="text-cyber-cyan font-mono">{user?.domain}</span>
        </p>
      </div>

      {/* ════════════ STEP 1 — DNS Verification ════════════ */}
      <GlowCard glow={isVerified ? 'green' : 'cyan'} className="p-6">
        <StepHeader step={1} title="DNS Domain Verification" subtitle="Prove ownership of your domain via TXT record" active={!isVerified} completed={isVerified} />

        {isVerified ? (
          <div className="flex items-center gap-2 px-4 py-3 bg-cyber-green/10 border border-cyber-green/20 rounded-lg">
            <CheckCircle2 className="w-5 h-5 text-cyber-green" />
            <span className="text-sm text-cyber-green font-semibold">Domain verified</span>
            <span className="ml-auto text-xs text-cyber-dim font-mono">
              {user?.verifiedAt ? new Date(user.verifiedAt).toLocaleDateString() : ''}
            </span>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-cyber-text leading-relaxed">
              Add the following <strong className="text-white">TXT record</strong> to your domain's DNS configuration:
            </p>

            {/* Token block */}
            <div className="relative bg-cyber-bg rounded-lg border border-cyber-border p-4 font-mono text-xs">
              <div className="text-cyber-dim mb-1">Type: <span className="text-white">TXT</span> &nbsp;|&nbsp; Host: <span className="text-white">@</span></div>
              <div className="text-cyber-cyan break-all select-all">{user?.verificationToken || '...'}</div>
              <button
                onClick={() => copyToClipboard(user?.verificationToken || '', setCopiedToken)}
                className="absolute top-3 right-3 p-1.5 rounded-md bg-cyber-card hover:bg-cyber-card2 transition-colors"
              >
                {copiedToken ? <Check className="w-3.5 h-3.5 text-cyber-green" /> : <Copy className="w-3.5 h-3.5 text-cyber-dim" />}
              </button>
            </div>

            {/* Verify button */}
            <button onClick={handleVerify} disabled={verifying} className="btn-cyber flex items-center gap-2">
              {verifying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Globe className="w-4 h-4" />}
              {verifying ? 'Querying DNS…' : 'Verify DNS Record'}
            </button>

            {dnsResult && (
              <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm animate-slide-in ${
                dnsResult.ok
                  ? 'bg-cyber-green/10 border border-cyber-green/20 text-cyber-green'
                  : 'bg-cyber-red/10 border border-cyber-red/20 text-cyber-red'
              }`}>
                {dnsResult.ok ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                {dnsResult.msg}
              </div>
            )}
          </div>
        )}
      </GlowCard>

      {/* ════════════ STEP 2 — Key Provisioning ════════════ */}
      <GlowCard glow={isVerified ? 'cyan' : 'none'} className={`p-6 transition-opacity duration-500 ${isVerified ? '' : 'opacity-50'}`}>
        <StepHeader
          step={2}
          title="Agent Key Provisioning"
          subtitle="Generate cryptographic sensor keys"
          active={isVerified && keys.length === 0}
          completed={keys.length > 0}
        />

        {!isVerified && (
          <div className="flex items-center gap-2 text-xs text-cyber-dim">
            <Lock className="w-4 h-4" />
            <span>Complete DNS verification to unlock key generation</span>
          </div>
        )}

        {isVerified && (
          <div className="space-y-4">
            {/* Generate form */}
            <div className="flex gap-3">
              <input
                type="text"
                placeholder="Key label (e.g. prod-sensor-01)"
                value={keyLabel}
                onChange={(e) => setKeyLabel(e.target.value)}
                className="input-cyber flex-1"
              />
              <button onClick={handleGenerateKey} disabled={generating} className="btn-cyber flex items-center gap-2 whitespace-nowrap">
                {generating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Key className="w-4 h-4" />}
                Generate Key
              </button>
            </div>

            {/* Existing keys */}
            {keys.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs text-cyber-dim uppercase tracking-wider font-semibold">Active Keys</p>
                {keys.map((k) => (
                  <div key={k._id} className="flex items-center justify-between px-4 py-3 bg-cyber-bg rounded-lg border border-cyber-border">
                    <div className="flex items-center gap-3">
                      <Key className="w-4 h-4 text-cyber-cyan" />
                      <span className="font-mono text-sm text-white">{k.keyPrefix}••••••••</span>
                      <span className="text-xs text-cyber-dim">{k.label}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-cyber-dim">
                      {k.lastIngestAt && (
                        <span>Last ingest: {new Date(k.lastIngestAt).toLocaleString()}</span>
                      )}
                      <span className={`status-pill ${k.isActive ? 'bg-cyber-green/10 text-cyber-green border border-cyber-green/20' : 'bg-cyber-red/10 text-cyber-red border border-cyber-red/20'}`}>
                        {k.isActive ? 'ACTIVE' : 'REVOKED'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </GlowCard>

      {/* ════════════ STEP 3 — Deployment ════════════ */}
      <GlowCard glow={isVerified ? 'cyan' : 'none'} className={`p-6 transition-opacity duration-500 ${isVerified ? '' : 'opacity-50'}`}>
        <StepHeader
          step={3}
          title="Sensor Deployment"
          subtitle="Download and deploy the edge sensor"
          active={isVerified && keys.length > 0}
          completed={false}
        />

        {!isVerified ? (
          <div className="flex items-center gap-2 text-xs text-cyber-dim">
            <Lock className="w-4 h-4" />
            <span>Complete previous steps first</span>
          </div>
        ) : (
          <div className="space-y-5">
            {/* Downloads */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <a
                href="/sensor/sensor.py"
                download="sensor.py"
                className="flex items-center gap-3 px-4 py-3 bg-cyber-bg rounded-lg border border-cyber-border hover:border-cyber-cyan/30 transition-all group"
              >
                <Download className="w-5 h-5 text-cyber-cyan group-hover:scale-110 transition-transform" />
                <div>
                  <p className="text-sm font-semibold text-white">sensor.py</p>
                  <p className="text-[10px] text-cyber-dim">Python edge sensor agent</p>
                </div>
              </a>
              <a
                href="/sensor/Dockerfile"
                download="Dockerfile"
                className="flex items-center gap-3 px-4 py-3 bg-cyber-bg rounded-lg border border-cyber-border hover:border-cyber-cyan/30 transition-all group"
              >
                <Download className="w-5 h-5 text-cyber-cyan group-hover:scale-110 transition-transform" />
                <div>
                  <p className="text-sm font-semibold text-white">Dockerfile</p>
                  <p className="text-[10px] text-cyber-dim">Container build file</p>
                </div>
              </a>
            </div>

            {/* Docker command */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="w-4 h-4 text-cyber-cyan" />
                <span className="text-xs text-cyber-dim uppercase tracking-wider font-semibold">Deployment Command</span>
              </div>
              <div className="relative bg-cyber-bg rounded-lg border border-cyber-border p-4">
                <pre className="text-xs font-mono text-cyber-green whitespace-pre-wrap select-all">{dockerCmd}</pre>
                <button
                  onClick={() => copyToClipboard(dockerCmd, setCopiedCmd)}
                  className="absolute top-3 right-3 p-1.5 rounded-md bg-cyber-card hover:bg-cyber-card2 transition-colors"
                >
                  {copiedCmd ? <Check className="w-3.5 h-3.5 text-cyber-green" /> : <Copy className="w-3.5 h-3.5 text-cyber-dim" />}
                </button>
              </div>
            </div>

            {/* Instructions */}
            <div className="px-4 py-3 bg-cyber-card2/50 rounded-lg border border-cyber-border text-xs text-cyber-text leading-relaxed space-y-2">
              <div className="flex items-center gap-2 text-cyber-cyan font-semibold">
                <ChevronRight className="w-3 h-3" /> Quick Start
              </div>
              <ol className="list-decimal list-inside space-y-1 pl-2">
                <li>Build the Docker image: <code className="text-cyber-green">docker build -t cyberadapt-sensor .</code></li>
                <li>Replace <code className="text-cyber-amber">ca_live_...</code> with your actual sensor key</li>
                <li>Update <code className="text-cyber-amber">INGEST_URL</code> if your API endpoint differs</li>
                <li>Run the container with <code className="text-cyber-green">--net=host</code> for network access</li>
              </ol>
            </div>
          </div>
        )}
      </GlowCard>

      {/* ── Key Modal (Overlay) ── */}
      {rawKey && <KeyModal rawKey={rawKey} onClose={() => setRawKey(null)} />}
    </div>
  );
}
