import React from 'react';
import { AlertTriangle, ShieldAlert, Zap, Info } from 'lucide-react';

export default function AttackAlertBanner({ flows }) {
  // Find recent attack flows in the telemetry log
  const attackFlows = (flows || []).filter(
    (f) => f.threatLabel && f.threatLabel !== 'Normal Traffic'
  );

  if (attackFlows.length === 0) {
    return (
      <div className="p-4 bg-cyber-green/10 border border-cyber-green/30 rounded-lg flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 rounded-full bg-cyber-green animate-pulse" />
          <div>
            <h3 className="text-xs font-bold font-mono text-cyber-green uppercase tracking-wider">
              SYSTEM STATUS: NOMINAL (NO ACTIVE ATTACKS DETECTED)
            </h3>
            <p className="text-[11px] text-cyber-dim font-mono">
              Labrooms 10-feature application-layer model is actively monitoring HTTP telemetry
            </p>
          </div>
        </div>
        <span className="text-xs font-mono text-cyber-green bg-cyber-green/20 px-3 py-1 rounded font-bold">
          SECURE
        </span>
      </div>
    );
  }

  // Get the most critical active attack
  const primaryAttack = attackFlows[0];
  const label = primaryAttack.threatLabel;
  const features = primaryAttack.features || [];
  const durationUs = features[1] || 0;
  const fwdBytes = features[4] || 0;
  const bwdBytes = features[5] || 0;
  const statusCode = features[44] || 200;

  // Determine threat explanation based on Labrooms feature contract
  let explanation = "";
  if (label.includes('DoS')) {
    explanation = `Triggered by Flow Duration = ${(durationUs / 1e6).toFixed(1)}s (Slowloris threshold >30s) & HTTP Status Code ${statusCode}`;
  } else if (label.includes('Web') || label.includes('Exfil')) {
    explanation = `Triggered by Response Size = ${(bwdBytes / 1e6).toFixed(1)} MB (Data Exfiltration payload >10 MB) or HTTP Status Code ${statusCode}`;
  } else if (label.includes('Brute')) {
    explanation = `Triggered by High Flow Throughput & HTTP Status Code ${statusCode} (Unauthorized Credential Stuffing Surge)`;
  } else {
    explanation = `Triggered by Anomaly in HTTP Status ${statusCode} & Request/Response Payload Ratios`;
  }

  return (
    <div className="p-5 bg-red-950/40 border-2 border-red-500 rounded-lg shadow-[0_0_25px_rgba(239,68,68,0.3)] animate-pulse space-y-3">
      <div className="flex items-center justify-between border-b border-red-500/30 pb-3">
        <div className="flex items-center gap-3">
          <ShieldAlert className="w-6 h-6 text-red-400 animate-bounce" />
          <div>
            <h2 className="text-sm font-bold text-red-400 font-mono uppercase tracking-widest flex items-center gap-2">
              ⚠️ CRITICAL THREAT DETECTED: {label.toUpperCase()}
            </h2>
            <p className="text-xs text-red-200 font-mono font-bold mt-0.5">
              Flow ID: <span className="text-white">{primaryAttack.flowId}</span> (Confidence: {((primaryAttack.threatConfidence || 0.95) * 100).toFixed(1)}%)
            </p>
          </div>
        </div>
        <span className="px-3 py-1 bg-red-500 text-white font-mono text-xs font-extrabold rounded animate-pulse">
          HIGH RISK ALERT
        </span>
      </div>

      <div className="bg-black/60 p-3 rounded border border-red-500/40 space-y-1 font-mono text-xs">
        <div className="flex items-center gap-2 text-red-300 font-bold">
          <Zap className="w-4 h-4 text-yellow-400" />
          DETECTION REASON & FEATURE ATTRIBUTION:
        </div>
        <p className="text-white font-mono pl-6">{explanation}</p>
        <div className="pl-6 pt-1 text-[11px] text-gray-400 flex flex-wrap gap-4">
          <span>Duration: <strong className="text-cyber-cyan">{(durationUs / 1e6).toFixed(2)}s</strong></span>
          <span>Req Size: <strong className="text-cyber-cyan">{fwdBytes} B</strong></span>
          <span>Res Size: <strong className="text-cyber-purple">{(bwdBytes / 1024).toFixed(1)} KB</strong></span>
          <span>HTTP Code: <strong className="text-yellow-400">{statusCode}</strong></span>
        </div>
      </div>
    </div>
  );
}
