/* ──────────────────────────────────────────────────────────────
   LiveTrafficTable — Auto-refreshing recent traffic flows with ML predictions & charts
   ────────────────────────────────────────────────────────────── */
import { useState, useEffect, useRef } from 'react';
import { Activity, ArrowDown, ShieldAlert, ShieldCheck } from 'lucide-react';
import api from '../api';
import TrafficSpikeChart from './TrafficSpikeChart';

/* ── Feature-index mapping for Labrooms 10-feature display columns ── */
const F = {
  DURATION:    1,   // Flow Duration (µs)
  FWD_PKTS:    2,   // Total Fwd Packets
  BWD_PKTS:    3,   // Total Backward Packets
  FWD_BYTES:   4,   // Total Length of Fwd Packets (Request Size)
  BWD_BYTES:   5,   // Total Length of Bwd Packets (Response Size)
  STATUS_CODE: 44,  // SYN Slot hijacked for HTTP Status Code (200, 404, 500)
};

function formatDuration(us) {
  if (us < 1000) return `${us.toFixed(0)}µs`;
  if (us < 1_000_000) return `${(us / 1000).toFixed(1)}ms`;
  return `${(us / 1_000_000).toFixed(2)}s`;
}

function extractIpPort(flowId) {
  const parts = flowId.split('-');
  return {
    src: parts[0] || '—',
    dst: parts[1] || '—',
  };
}

function formatBytes(b) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1048576).toFixed(2)} MB`;
}

function ThreatBadge({ label, confidence }) {
  if (!label || label === 'Normal Traffic') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-cyber-green/10 text-cyber-green border border-cyber-green/30 text-xs font-mono font-bold rounded">
        <span className="w-1.5 h-1.5 rounded-full bg-cyber-green" />
        Normal {confidence ? `(${(confidence * 100).toFixed(0)}%)` : ''}
      </span>
    );
  }

  const isDos = label.includes('DoS') || label.includes('DDoS');
  const isBrute = label.includes('Brute');

  const badgeStyle = isDos
    ? 'bg-red-500/20 text-red-400 border-red-500/40 shadow-[0_0_10px_rgba(255,0,85,0.3)]'
    : isBrute
    ? 'bg-amber-500/20 text-amber-400 border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.3)]'
    : 'bg-purple-500/20 text-purple-400 border-purple-500/40 shadow-[0_0_10px_rgba(168,85,247,0.3)]';

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 border text-xs font-mono font-bold rounded ${badgeStyle}`}>
      <ShieldAlert className="w-3.5 h-3.5 animate-pulse" />
      {label} {confidence ? `(${(confidence * 100).toFixed(1)}%)` : ''}
    </span>
  );
}

export default function LiveTrafficTable() {
  const [flows, setFlows] = useState([]);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  async function fetchFlows() {
    try {
      const data = await api.get('/telemetry/recent-flows');
      setFlows(data.flows || []);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    fetchFlows();
    intervalRef.current = setInterval(fetchFlows, 3000);
    return () => clearInterval(intervalRef.current);
  }, []);

  return (
    <div className="w-full space-y-6">
      {/* Real-time Traffic Spike Chart */}
      <TrafficSpikeChart flows={flows} />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-cyber-cyan" strokeWidth={1.5} />
          <h2 className="text-sm font-bold tracking-[0.15em] text-white uppercase">
            Live Telemetry Flows & ML Model Predictions
          </h2>
          <span className="status-pill bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20">
            <span className="w-1.5 h-1.5 rounded-full bg-cyber-cyan status-dot-pulse" />
            LIVE INFERENCE
          </span>
        </div>
        <span className="text-xs text-cyber-dim font-mono">{flows.length} recent flows</span>
      </div>

      {error && (
        <div className="mb-3 px-4 py-2 bg-cyber-red/10 border border-cyber-red/20 rounded-lg text-xs text-cyber-red font-mono">
          {error}
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-cyber-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-cyber-card2/80 text-cyber-text uppercase tracking-wider">
              <th className="px-4 py-3 text-left font-semibold">Time</th>
              <th className="px-4 py-3 text-left font-semibold">Flow ID / Endpoints</th>
              <th className="px-4 py-3 text-right font-semibold">Duration</th>
              <th className="px-4 py-3 text-right font-semibold">Req / Res Bytes</th>
              <th className="px-4 py-3 text-center font-semibold">HTTP Code [44]</th>
              <th className="px-4 py-3 text-center font-semibold">ML Model Prediction</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-cyber-border/50">
            {flows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-cyber-dim font-mono">
                  <ArrowDown className="w-5 h-5 mx-auto mb-2 opacity-40 animate-bounce" />
                  Awaiting telemetry flows from sensor…
                </td>
              </tr>
            )}
            {flows.map((flow, i) => {
              const { src, dst } = extractIpPort(flow.flowId || '');
              const f = flow.features || [];
              const duration   = f[F.DURATION] || 0;
              const fwdBytes   = f[F.FWD_BYTES] || 0;
              const bwdBytes   = f[F.BWD_BYTES] || 0;
              const statusCode = f[F.STATUS_CODE] || 200;
              const time = new Date(flow.receivedAt).toLocaleTimeString('en-US', { hour12: false });

              return (
                <tr
                  key={flow._id || i}
                  className="hover:bg-cyber-cyan/5 transition-colors duration-200 animate-fade-in"
                >
                  <td className="px-4 py-3 font-mono text-cyber-text">{time}</td>
                  <td className="px-4 py-3 font-mono">
                    <div className="text-white font-bold">{flow.flowId}</div>
                    <div className="text-[10px] text-cyber-dim">{src} &rarr; {dst}</div>
                  </td>
                  <td className="px-4 py-3 font-mono text-right text-cyber-amber">
                    {formatDuration(duration)}
                  </td>
                  <td className="px-4 py-3 font-mono text-right">
                    <span className="text-cyber-cyan">{formatBytes(fwdBytes)}</span> / <span className="text-cyber-purple">{formatBytes(bwdBytes)}</span>
                  </td>
                  <td className="px-4 py-3 font-mono text-center">
                    <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                      statusCode >= 500 ? 'bg-red-500/20 text-red-400 border border-red-500/30' :
                      statusCode >= 400 ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                      'bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20'
                    }`}>
                      {statusCode}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <ThreatBadge label={flow.threatLabel} confidence={flow.threatConfidence} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
