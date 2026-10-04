import React, { useState, useEffect, useRef } from 'react';
import api from '../api';

/* Short axis labels for the 7-class confusion matrix ("Normal Traffic" -> "Normal") */
const shortName = (n) => (n || '').split(' ')[0];
const fmtPct = (v) => (v != null ? `${(v * 100).toFixed(1)}%` : '—');

export default function Evaluation() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef(null);

  async function fetchMetrics() {
    try {
      const res = await api.get('/telemetry/evaluation');
      setData(res);
    } catch {
      /* ML API offline / 503 — keep last good snapshot */
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchMetrics();
    intervalRef.current = setInterval(fetchMetrics, 3000);
    return () => clearInterval(intervalRef.current);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
      </div>
    );
  }

  const overall     = data?.overall_metrics || {};
  const win         = data?.window || {};
  const insufficient = !!data?.insufficient_data;
  const perClass    = Object.entries(data?.per_class_metrics || {});
  const classNames  = data?.class_names || [];
  const cm          = data?.confusion_matrix || [];
  const cmMax       = Math.max(1, ...cm.flat());
  const pp          = data?.pre_post_adaptation || {};
  const showPrePost = pp.last_adaptation != null && pp.post != null;
  const ppDelta     = showPrePost ? (pp.post.f1_macro ?? 0) - (pp.pre?.f1_macro ?? 0) : 0;

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-cyber-border/40 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-wider text-white uppercase flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-cyber-green rounded-full animate-pulse inline-block" />
            Model Evaluation & Performance Benchmarks
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            Live rolling-window metrics on pseudo-labeled stream traffic
          </p>
        </div>
        {data && (
          <span className="status-pill bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/20">
            <span className="w-1.5 h-1.5 rounded-full bg-cyber-cyan status-dot-pulse" />
            LIVE WINDOW {win.size ?? 0}/{win.capacity ?? '—'}
          </span>
        )}
      </div>

      {/* Pre / Post Adaptation strip — hidden until a promotion lands */}
      {showPrePost && (
        <div className="p-4 bg-cyber-surface/40 border border-cyber-border rounded-lg font-mono flex flex-wrap items-center gap-x-6 gap-y-2 text-xs">
          <span className="text-[10px] text-cyber-dim uppercase tracking-wider">Pre / Post Adaptation</span>
          <span className="text-gray-300">
            F1 <span className="text-cyber-amber font-bold">{fmtPct(pp.pre?.f1_macro)}</span>
            <span className="text-cyber-dim mx-1.5">→</span>
            <span className="text-cyber-green font-bold">{fmtPct(pp.post?.f1_macro)}</span>
          </span>
          <span className={`font-bold ${ppDelta >= 0 ? 'text-cyber-green' : 'text-cyber-red'}`}>
            {ppDelta >= 0 ? '▲' : '▼'} {(Math.abs(ppDelta) * 100).toFixed(1)}%
          </span>
          <span className="text-cyber-dim">
            {pp.pre?.samples ?? 0} → {pp.post?.samples ?? 0} samples · last {pp.last_adaptation}
          </span>
        </div>
      )}

      {insufficient ? (
        /* Muted state while the rolling window fills with labeled flows */
        <div className="p-10 bg-cyber-surface/40 border border-cyber-border rounded-lg text-center font-mono">
          <p className="text-sm text-cyber-dim uppercase tracking-wider">
            Collecting labeled stream samples…
          </p>
          <p className="text-xs text-cyber-dim/70 mt-2">
            {win.size ?? 0} pseudo-labeled flows in window — metrics appear once ≥30 labeled samples are buffered
          </p>
        </div>
      ) : (
        <>
          {/* Metric Cards */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4 font-mono">
            <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg text-center">
              <p className="text-[10px] text-cyber-dim uppercase">Accuracy</p>
              <div className="text-xl font-bold text-cyber-green mt-1">
                {fmtPct(overall.accuracy)}
              </div>
            </div>

            <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg text-center">
              <p className="text-[10px] text-cyber-dim uppercase">Precision (Macro)</p>
              <div className="text-xl font-bold text-cyber-cyan mt-1">
                {fmtPct(overall.precision_macro)}
              </div>
            </div>

            <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg text-center">
              <p className="text-[10px] text-cyber-dim uppercase">Recall (Macro)</p>
              <div className="text-xl font-bold text-cyber-purple mt-1">
                {fmtPct(overall.recall_macro)}
              </div>
            </div>

            <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg text-center">
              <p className="text-[10px] text-cyber-dim uppercase">F1 Score (Macro)</p>
              <div className="text-xl font-bold text-yellow-400 mt-1">
                {fmtPct(overall.f1_macro)}
              </div>
            </div>

            <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg text-center">
              <p className="text-[10px] text-cyber-dim uppercase">P95 Latency</p>
              <div className="text-xl font-bold text-white mt-1">
                {overall.latency_p95_ms != null ? `${overall.latency_p95_ms.toFixed(1)} ms` : '—'}
              </div>
            </div>
          </div>

          {/* Per Class Metrics Table */}
          <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
              Per-Attack-Class Performance Matrix
            </h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left font-mono text-xs">
                <thead>
                  <tr className="border-b border-cyber-border text-cyber-dim uppercase">
                    <th className="py-2 px-3">Attack Class</th>
                    <th className="py-2 px-3">Precision</th>
                    <th className="py-2 px-3">Recall</th>
                    <th className="py-2 px-3">F1 Score</th>
                    <th className="py-2 px-3">Support</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-cyber-border/40 text-gray-300">
                  {perClass.map(([cls, m], idx) => (
                    <tr key={idx}>
                      <td className="py-3 px-3 font-bold text-white">{cls}</td>
                      <td className="py-3 px-3 text-cyber-cyan">{fmtPct(m.precision)}</td>
                      <td className="py-3 px-3 text-cyber-purple">{fmtPct(m.recall)}</td>
                      <td className="py-3 px-3 font-bold text-cyber-green">{fmtPct(m.f1)}</td>
                      <td className="py-3 px-3 text-cyber-dim">{m.support ?? '—'}</td>
                    </tr>
                  ))}
                  {perClass.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-6 px-3 text-center text-cyber-dim">
                        No labeled classes in the rolling window yet…
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Confusion Matrix — 7x7 live window */}
          <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
              Live Confusion Matrix
            </h2>
            <div className="overflow-x-auto">
              <div
                className="min-w-[560px] font-mono text-[10px] grid"
                style={{ gridTemplateColumns: `110px repeat(${classNames.length || 7}, minmax(0, 1fr))` }}
              >
                <div className="px-2 py-1 text-cyber-dim uppercase">Actual ↓ / Pred →</div>
                {classNames.map((n, c) => (
                  <div key={c} title={n} className="px-1 py-1 text-center text-cyber-dim truncate">
                    {shortName(n)}
                  </div>
                ))}
                {cm.map((row, r) => (
                  <React.Fragment key={r}>
                    <div title={classNames[r]} className="px-2 py-1 text-cyber-dim truncate flex items-center">
                      {shortName(classNames[r])}
                    </div>
                    {row.map((v, c) => {
                      const diag = r === c;
                      const a = v === 0 ? 0 : 0.06 + (v / cmMax) * 0.3;
                      return (
                        <div
                          key={c}
                          className={`px-1 py-1.5 text-center border border-cyber-border/20 ${
                            v === 0 ? 'text-cyber-dim/40' : diag ? 'text-cyber-green font-bold' : 'text-cyber-red'
                          }`}
                          style={{
                            backgroundColor: v === 0
                              ? 'transparent'
                              : diag
                                ? `rgba(0, 255, 157, ${a})`
                                : `rgba(255, 46, 86, ${a})`,
                          }}
                        >
                          {v}
                        </div>
                      );
                    })}
                  </React.Fragment>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
