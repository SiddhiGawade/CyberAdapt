import React, { useState, useEffect, useRef } from 'react';
import { ShieldAlert } from 'lucide-react';
import api from '../api';

/* ── Static display metadata (NOT live metrics) ───────────────────────────
   Slot → human meaning for the API's short `name` in labrooms_features_drift. */
const SLOT_MEANINGS = {
  1:  'Flow Duration (microseconds)',
  4:  'Total Fwd Bytes (HTTP Request Size)',
  5:  'Total Bwd Bytes (HTTP Response Size / Exfiltration)',
  14: 'Flow Bytes/s (Throughput / Scraping)',
  44: 'SYN Count (Hijacked for HTTP Status Code: 200/404/500)',
};

const DRIFT_STATE_META = {
  stable:  { label: 'NO DRIFT',       cls: 'text-cyber-green', sub: 'Stable feature distribution' },
  warning: { label: 'WARNING',        cls: 'text-yellow-400',  sub: 'Minor distribution shift detected' },
  drift:   { label: 'DRIFT DETECTED', cls: 'text-cyber-red',   sub: 'Adaptation pipeline engaged' },
};

const PSI_STATUS_CHIP = {
  stable:      { label: 'STABLE',      cls: 'text-cyber-green' },
  minor_shift: { label: 'MINOR SHIFT', cls: 'text-yellow-400' },
  drifted:     { label: 'DRIFTED',     cls: 'text-cyber-red' },
};

/* Detector key → card title + live fields (§8 detector_algorithms shape).
   int: render raw integer; otherwise fixed-3 float; null → '—'. */
const DETECTOR_CARDS = [
  { key: 'ADWIN_attack_ratio', title: 'ADWIN', fields: [
    { label: 'est',          field: 'estimation' },
    { label: 'width',        field: 'width', int: true },
  ]},
  { key: 'DDM_pseudo_error', title: 'DDM', fields: [
    { label: 'error_rate',   field: 'error_rate' },
    { label: 'warning_lvl',  field: 'warning_level' },
  ]},
  { key: 'PageHinkley', title: 'Page-Hinkley', fields: [
    { label: 'sum_val',      field: 'sum_val' },
    { label: 'threshold',    field: 'threshold' },
  ]},
  { key: 'KS_Test', title: 'Kolmogorov-Smirnov', fields: [
    { label: 'KS-stat',      field: 'stat' },
    { label: 'p-val',        field: 'p_value' },
  ]},
];

const fmtVal = (v, int) => {
  if (v === null || v === undefined) return '—';
  return int ? Number(v).toLocaleString() : Number(v).toFixed(3);
};

const fmtTs = (ts) => (ts ? new Date(ts).toLocaleString() : '—');

function DetectorBadge({ det }) {
  const drift = det?.drift_signal === true;
  const warn = !drift && det?.status === 'warning';
  const label = drift ? 'DRIFT' : warn ? 'WARNING' : 'STABLE';
  const cls = drift
    ? 'bg-cyber-red/20 text-cyber-red'
    : warn
      ? 'bg-yellow-400/20 text-yellow-400'
      : 'bg-cyber-green/20 text-cyber-green';
  return <span className={`text-[10px] ${cls} px-2 py-0.5 rounded font-mono`}>{label}</span>;
}

export default function ConceptDrift() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);

  useEffect(() => {
    let mounted = true;

    async function fetchDrift() {
      try {
        const res = await api.get('/telemetry/concept-drift');
        if (mounted) {
          setData(res);
          setError(null);
          setLoading(false);
        }
      } catch (err) {
        if (mounted) {
          setError(err.message);   // keep last good data — nothing scary
          setLoading(false);
        }
      }
    }

    fetchDrift();
    intervalRef.current = setInterval(fetchDrift, 3000);
    return () => {
      mounted = false;
      clearInterval(intervalRef.current);
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
      </div>
    );
  }

  const driftMeta = DRIFT_STATE_META[data?.drift_state] || DRIFT_STATE_META.stable;
  const features = data?.labrooms_features_drift || [];
  const events = data?.drift_events || [];

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-cyber-border/40 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-wider text-white uppercase flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-cyber-cyan rounded-full animate-pulse inline-block" />
            Streaming Concept Drift Detection
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            Real-time distributional shift monitoring for Labrooms application-layer telemetry
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-3 py-1 bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan text-xs font-mono rounded">
            STATUS: {data?.status === 'warming_up' ? 'WARMING UP' : 'ACTIVE MONITORING'}
          </span>
        </div>
      </div>

      {/* Full-width drift alert — latched while drift_detected === true */}
      {data?.drift_detected === true && (
        <div className="p-5 bg-red-950/40 border-2 border-red-500 rounded-lg shadow-[0_0_25px_rgba(239,68,68,0.3)] animate-pulse">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <ShieldAlert className="w-6 h-6 text-red-400 animate-bounce" />
              <div>
                <h2 className="text-sm font-bold text-red-400 font-mono uppercase tracking-widest">
                  ⚠️ CONCEPT DRIFT DETECTED — ADAPTATION PIPELINE ENGAGED
                </h2>
                <p className="text-xs text-red-200 font-mono font-bold mt-0.5">
                  Last drift: <span className="text-white">{fmtTs(data?.last_drift_timestamp)}</span>
                  {events[0]?.detail ? <span className="text-red-300"> — {events[0].detail}</span> : null}
                </p>
              </div>
            </div>
            <span className="px-3 py-1 bg-red-500 text-white font-mono text-xs font-extrabold rounded animate-pulse">
              DRIFT ACTIVE
            </span>
          </div>
        </div>
      )}

      {error && (
        <div className="px-4 py-2 bg-cyber-red/10 border border-cyber-red/20 rounded-lg text-xs text-cyber-red font-mono">
          {error} — showing last known state
        </div>
      )}

      {/* Summary Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Drift Signal</p>
          <div className={`text-2xl font-bold ${driftMeta.cls} mt-1 flex items-center gap-2`}>
            <span>{driftMeta.label}</span>
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">
            {data?.last_drift_timestamp ? `Last drift: ${fmtTs(data.last_drift_timestamp)}` : driftMeta.sub}
          </p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Samples Since Retrain</p>
          <div className="text-2xl font-bold text-cyber-cyan mt-1 font-mono">
            {data?.samples_processed_since_retrain?.toLocaleString() ?? '—'}
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">
            Total processed: {data?.samples_processed?.toLocaleString() ?? '—'}
          </p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Detector Suite</p>
          <div className="text-2xl font-bold text-white mt-1 font-mono">
            {Object.keys(data?.detector_algorithms || {}).length || '—'} Algorithms
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">ADWIN, DDM, PH, KS</p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Active Contract</p>
          <div className="text-2xl font-bold text-cyber-purple mt-1 font-mono">Labrooms-10</div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">42 zeroed slots filtered</p>
        </div>
      </div>

      {/* Detector Algorithms Detail */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Online Drift Detectors Status
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {DETECTOR_CARDS.map(({ key, title, fields }) => {
            const det = data?.detector_algorithms?.[key];
            return (
              <div key={key} className="p-4 bg-black/40 border border-cyber-border/60 rounded">
                <div className="flex justify-between items-center mb-2">
                  <span className="font-bold text-white text-xs">{title}</span>
                  <DetectorBadge det={det} />
                </div>
                {fields.map(({ label, field, int }) => (
                  <p key={field} className="text-xs font-mono text-cyber-dim">
                    {label}: <span className="text-white">{fmtVal(det?.[field], int)}</span>
                  </p>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* Labrooms Feature Drift Table */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Labrooms Populated Feature Drift Breakdown
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-cyber-border text-cyber-dim uppercase">
                <th className="py-2 px-3">Slot Index</th>
                <th className="py-2 px-3">Feature Name &amp; Meaning</th>
                <th className="py-2 px-3">Drift Score</th>
                <th className="py-2 px-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cyber-border/40 text-gray-300">
              {features.map((f) => {
                const chip = PSI_STATUS_CHIP[f?.status] || PSI_STATUS_CHIP.stable;
                return (
                  <tr key={f.slot}>
                    <td className="py-3 px-3 text-cyber-cyan">[{f.slot}]</td>
                    <td className="py-3 px-3">{SLOT_MEANINGS[f.slot] || f.name}</td>
                    <td className="py-3 px-3 font-mono">{fmtVal(f.drift)}</td>
                    <td className="py-3 px-3"><span className={chip.cls}>{chip.label}</span></td>
                  </tr>
                );
              })}
              {features.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 px-3 text-center text-cyber-dim">
                    Awaiting drift telemetry…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Recent Drift Events */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Recent Drift Events
        </h2>
        <div className="space-y-2 font-mono text-xs">
          {events.length === 0 && (
            <p className="text-cyber-dim">No drift events recorded this session.</p>
          )}
          {events.map((ev, i) => (
            <div
              key={`${ev?.timestamp || 'ev'}-${i}`}
              className="p-3 bg-black/40 border border-cyber-border/60 rounded flex flex-col md:flex-row md:items-center gap-2 md:gap-4"
            >
              <span className="text-cyber-dim shrink-0">{fmtTs(ev?.timestamp)}</span>
              <span className="px-2 py-0.5 rounded bg-cyber-red/20 text-cyber-red text-[10px] font-bold shrink-0 w-fit">
                {ev?.detector || '—'}
              </span>
              <span className="text-cyber-cyan shrink-0">{ev?.signal || '—'}</span>
              <span className="text-gray-300 flex-1">{ev?.detail || '—'}</span>
              <span className="text-cyber-dim shrink-0">
                @ {ev?.samples_processed != null ? Number(ev.samples_processed).toLocaleString() : '—'} samples
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
