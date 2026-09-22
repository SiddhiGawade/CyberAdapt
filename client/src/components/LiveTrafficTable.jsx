/* ──────────────────────────────────────────────────────────────
   LiveTrafficTable — Auto-refreshing recent traffic flows
   ────────────────────────────────────────────────────────────── */
import { useState, useEffect, useRef } from 'react';
import { Activity, ArrowDown } from 'lucide-react';
import api from '../api';

/* ── Feature-index mapping for display columns ── */
const F = {
  DURATION:  1,   // Flow Duration (µs)
  FWD_PKTS:  2,   // Total Fwd Packets
  BWD_PKTS:  3,   // Total Backward Packets
  FWD_BYTES: 4,   // Total Length of Fwd Packets
  BWD_BYTES: 5,   // Total Length of Bwd Packets
};

function formatDuration(us) {
  if (us < 1000) return `${us.toFixed(0)}µs`;
  if (us < 1_000_000) return `${(us / 1000).toFixed(1)}ms`;
  return `${(us / 1_000_000).toFixed(2)}s`;
}

function extractIpPort(flowId) {
  /* flowId pattern: srcIp:srcPort-dstIp:dstPort-proto */
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

export default function LiveTrafficTable() {
  const [flows, setFlows]   = useState([]);
  const [error, setError]   = useState(null);
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
    <div className="w-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Activity className="w-5 h-5 text-cyber-cyan" strokeWidth={1.5} />
          <h2 className="text-sm font-bold tracking-[0.15em] text-white uppercase">
            Recent Traffic Flows
          </h2>
          <span className="status-pill bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20">
            <span className="w-1.5 h-1.5 rounded-full bg-cyber-cyan status-dot-pulse" />
            LIVE
          </span>
        </div>
        <span className="text-xs text-cyber-dim font-mono">{flows.length} records</span>
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
              <th className="px-4 py-3 text-left font-semibold">Source</th>
              <th className="px-4 py-3 text-left font-semibold">Destination</th>
              <th className="px-4 py-3 text-right font-semibold">Duration</th>
              <th className="px-4 py-3 text-right font-semibold">Pkts</th>
              <th className="px-4 py-3 text-right font-semibold">Bytes</th>
              <th className="px-4 py-3 text-center font-semibold">Prediction</th>
              <th className="px-4 py-3 text-center font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-cyber-border/50">
            {flows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-cyber-dim font-mono">
                  <ArrowDown className="w-5 h-5 mx-auto mb-2 opacity-40 animate-bounce" />
                  Awaiting telemetry…
                </td>
              </tr>
            )}
            {flows.map((flow, i) => {
              const { src, dst } = extractIpPort(flow.flowId || '');
              const f = flow.features || [];
              const totalPkts  = (f[F.FWD_PKTS] || 0) + (f[F.BWD_PKTS] || 0);
              const totalBytes = (f[F.FWD_BYTES] || 0) + (f[F.BWD_BYTES] || 0);
              const time = new Date(flow.receivedAt).toLocaleTimeString('en-US', { hour12: false });

              return (
                <tr
                  key={flow._id || i}
                  className="hover:bg-cyber-cyan/5 transition-colors duration-200 animate-fade-in"
                >
                  <td className="px-4 py-2.5 font-mono text-cyber-text">{time}</td>
                  <td className="px-4 py-2.5 font-mono text-white">{src}</td>
                  <td className="px-4 py-2.5 font-mono text-white">{dst}</td>
                  <td className="px-4 py-2.5 font-mono text-right text-cyber-amber">
                    {formatDuration(f[F.DURATION] || 0)}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-right">{totalPkts}</td>
                  <td className="px-4 py-2.5 font-mono text-right">{formatBytes(totalBytes)}</td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="status-pill bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20">
                      Ingested
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="status-pill bg-cyber-green/10 text-cyber-green border border-cyber-green/20">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyber-green" />
                      Normal
                    </span>
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
