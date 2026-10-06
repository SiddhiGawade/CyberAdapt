import React, { useState, useEffect } from 'react';
import api from '../api';

// Promotion gates emitted by LiveAdapter (ml/src/models/adaptive_engine.py
// PromotionGateConfig) — key -> demo-friendly label.
const GATE_LABELS = {
  gate_macro_f1: 'Macro-F1 Delta (>= -0.01)',
  gate_bal_acc: 'Balanced-Acc Delta (>= -0.01)',
  gate_emerged_recall: 'Emerged-Class Recall (>= 0.70)',
  gate_normal_fpr: 'Normal FPR (<= 0.05)',
};

const fmtTs = ts => (ts ? String(ts).replace('T', ' ').replace('Z', '') : '—');

export default function Adaptation() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [triggerMsg, setTriggerMsg] = useState(null);
  const [triggerBusy, setTriggerBusy] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      api.get('/telemetry/adaptation')
        .then(res => {
          if (mounted) {
            setData(res);
            setLoading(false);
          }
        })
        .catch(() => {
          if (mounted) setLoading(false);
        });
    };
    load();
    const id = setInterval(load, 3000);
    return () => { mounted = false; clearInterval(id); };
  }, []);

  // POST /api/telemetry/adaptation/trigger — Flask returns 202 queued /
  // 409 retrain running / 422 buffer insufficient; Node proxy collapses to
  // 503 only when Flask itself is unreachable.
  const handleForceAdaptation = async () => {
    setTriggerBusy(true);
    try {
      const { status, data: body } = await api.postWithStatus('/telemetry/adaptation/trigger');
      if (status === 202) {
        setTriggerMsg({ tone: 'ok', text: 'Adaptation queued — candidate retrain started' });
      } else if (status === 409) {
        setTriggerMsg({ tone: 'warn', text: 'Retrain already running — wait for it to finish' });
      } else if (status === 422) {
        setTriggerMsg({ tone: 'warn', text: body?.detail || 'Insufficient labeled buffer for retrain' });
      } else if (status === 503) {
        setTriggerMsg({ tone: 'err', text: 'ML offline — Flask API unreachable' });
      } else {
        setTriggerMsg({ tone: 'warn', text: `Unexpected response (${status})` });
      }
    } catch {
      setTriggerMsg({ tone: 'err', text: 'Request failed — Node API unreachable' });
    } finally {
      setTriggerBusy(false);
    }
  };

  const buffer = data?.online_learning_buffer;
  const labelSources = buffer?.label_sources || {};
  const history = data?.retraining_history || [];
  const latestReport = history[history.length - 1] || null;
  const gates = latestReport?.gates_passed || null;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-8 h-8 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-fade-in pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-cyber-border/40 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-wider text-white uppercase flex items-center gap-2">
            <span className="w-2.5 h-2.5 bg-cyber-purple rounded-full animate-pulse inline-block" />
            Model Adaptation & Online Learning Engine
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            Drift-triggered candidate retraining with gated champion promotion
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data?.adaptation_in_progress && (
            <span className="flex items-center gap-2 px-3 py-1.5 border border-cyber-amber/60 text-cyber-amber text-[11px] font-mono font-bold rounded">
              <span className="w-3 h-3 border-2 border-cyber-amber/30 border-t-cyber-amber rounded-full animate-spin inline-block" />
              RETRAINING…
            </span>
          )}
          <div className="flex flex-col items-end gap-1.5">
            <button
              onClick={handleForceAdaptation}
              disabled={triggerBusy}
              className="px-4 py-2 bg-cyber-purple/20 border border-cyber-purple text-cyber-purple hover:bg-cyber-purple/30 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-mono font-bold rounded transition-colors"
            >
              {triggerBusy ? 'TRIGGERING…' : 'FORCE ADAPTATION STEP'}
            </button>
            {triggerMsg && (
              <p
                className={`text-[11px] font-mono max-w-xs text-right ${
                  triggerMsg.tone === 'ok'
                    ? 'text-cyber-green'
                    : triggerMsg.tone === 'err'
                      ? 'text-cyber-red'
                      : 'text-cyber-amber'
                }`}
              >
                {triggerMsg.text}
              </p>
            )}
          </div>
        </div>
      </div>

      {!data && (
        <div className="p-3 border border-cyber-red/50 bg-cyber-red/10 text-cyber-red text-xs font-mono rounded">
          ML API offline — GET /api/telemetry/adaptation unreachable (retrying every 3 s)
        </div>
      )}

      {/* Model Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono">Champion Model</p>
          <div className="flex items-baseline gap-2 mt-1 font-mono">
            <span className="text-lg font-bold text-cyber-cyan">{data?.champion_model || '—'}</span>
            <span className="text-2xl font-bold text-cyber-amber">{data?.champion_version || '—'}</span>
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">Active in live inference pipeline</p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono">Adaptation Protocol</p>
          <div className="text-lg font-bold text-cyber-purple mt-1 font-mono">
            {data?.adaptation_mode || '—'}
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">Drift alert or manual trigger spawns gated candidate retrain</p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono">Online Buffer Status</p>
          <div className="text-lg font-bold text-cyber-green mt-1 font-mono">
            {buffer?.current_size ?? '—'} / {buffer?.capacity ?? '—'} flows
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">
            Buffer load: {buffer?.fill_percentage ?? '—'}%
          </p>
          <p className="text-[11px] text-cyber-dim font-mono mt-1">
            Labels — verified:{labelSources.verified_label || 0} · rule:{labelSources.rule_override || 0} · tag:{labelSources.flow_id_tag || 0}
          </p>
        </div>
      </div>

      {/* Promotion Gate Status — newest retraining_history entry's gate report.
          The champion is a single LightGBM, not the static ensemble, so the
          old weight bars now show the gates a candidate must pass. */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Promotion Gate Status
        </h2>
        {gates ? (
          <div className="space-y-3">
            <p className="text-[11px] text-cyber-dim font-mono">
              Latest candidate evaluation — {latestReport.version || '—'} · {latestReport.trigger || '—'}
            </p>
            {Object.entries(GATE_LABELS).map(([key, label]) => (
              <div key={key} className="flex items-center justify-between text-xs font-mono text-gray-300 border-b border-cyber-border/30 pb-2">
                <span>{label}</span>
                <span
                  className={`px-2 py-0.5 rounded border text-[10px] font-bold ${
                    gates[key] === true
                      ? 'border-cyber-green/60 text-cyber-green bg-cyber-green/10'
                      : 'border-cyber-red/60 text-cyber-red bg-cyber-red/10'
                  }`}
                >
                  {gates[key] === true ? 'PASS' : 'FAIL'}
                </span>
              </div>
            ))}
            {data?.last_event && (
              <p className="text-[11px] text-cyber-dim font-mono pt-1">
                Last event [{data.last_event.type}]: {data.last_event.detail}
              </p>
            )}
          </div>
        ) : (
          <p className="text-xs font-mono text-cyber-dim">
            No candidate evaluation yet — gates appear here after the first retrain.
          </p>
        )}
      </div>

      {/* Retraining & Adaptation History */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Model Version & Adaptation History
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-cyber-border text-cyber-dim uppercase">
                <th className="py-2 px-3">Version</th>
                <th className="py-2 px-3">Timestamp</th>
                <th className="py-2 px-3">F1 Macro Score</th>
                <th className="py-2 px-3">Trigger Event</th>
                <th className="py-2 px-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cyber-border/40 text-gray-300">
              {history.length ? (
                history.slice().reverse().map((item, idx) => (
                  <tr key={idx}>
                    <td className="py-3 px-3 font-bold text-cyber-cyan">{item.version || '—'}</td>
                    <td className="py-3 px-3">{fmtTs(item.timestamp)}</td>
                    <td className="py-3 px-3 font-bold text-cyber-green">
                      {item.f1_score != null ? `${(item.f1_score * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td className="py-3 px-3 text-gray-400">{item.trigger || '—'}</td>
                    <td className="py-3 px-3">
                      <span
                        className={`px-2 py-0.5 rounded border text-[10px] font-bold ${
                          item.promoted
                            ? 'border-cyber-green/60 text-cyber-green bg-cyber-green/10'
                            : 'border-cyber-red/60 text-cyber-red bg-cyber-red/10'
                        }`}
                      >
                        {item.promoted ? 'PROMOTED' : 'REJECTED'}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="py-4 px-3 text-center text-cyber-dim">
                    No retraining events recorded yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
