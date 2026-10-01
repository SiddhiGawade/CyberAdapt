import React, { useState, useEffect } from 'react';
import api from '../api';

export default function Explainability() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.get('/telemetry/explain')
      .then(res => {
        if (mounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => { mounted = false; };
  }, []);

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
            <span className="w-2.5 h-2.5 bg-yellow-400 rounded-full animate-pulse inline-block" />
            Explainability Engine (SHAP / Feature Attribution)
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            Global and local feature attributions for Labrooms 10-feature application-layer anomaly detection
          </p>
        </div>
      </div>

      {/* Labrooms 10-Feature Contract Banner */}
      <div className="p-4 bg-cyber-surface/60 border border-cyber-border/80 rounded-lg space-y-2">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 bg-cyber-cyan/20 text-cyber-cyan font-mono text-[11px] font-bold rounded">
            LABROOMS CONTRACT SPECS
          </span>
          <span className="text-xs font-mono text-gray-300">
            52 total CyberAdapt slots &rarr; 10 populated slots &rarr; 42 zeroed slots filtered to eliminate training-serving skew
          </span>
        </div>
      </div>

      {/* Global Feature Importances */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Global Feature Importance Breakdown
        </h2>
        <div className="space-y-4">
          {data?.feature_importances?.map((item, idx) => (
            <div key={idx}>
              <div className="flex justify-between text-xs font-mono text-gray-300 mb-1">
                <span className="flex items-center gap-2">
                  <span className="text-white font-bold">{item.name}</span>
                  <span className="text-[10px] text-cyber-dim">({item.category})</span>
                </span>
                <span className="text-cyber-cyan font-mono font-bold">
                  {(item.importance * 100).toFixed(1)}%
                </span>
              </div>
              <div className="w-full bg-black/60 h-2 rounded-full overflow-hidden border border-cyber-border/40">
                <div
                  className="bg-gradient-to-r from-cyber-cyan to-cyber-purple h-full rounded-full"
                  style={{ width: `${item.importance * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Labrooms 10-Feature Schema Reference */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Labrooms 10-Feature Vector Slot Specification
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 font-mono text-xs">
          {data?.labrooms_10_feature_breakdown?.map((slot, idx) => (
            <div key={idx} className="p-3 bg-black/40 border border-cyber-border/50 rounded flex justify-between items-center">
              <div>
                <span className="text-cyber-cyan font-bold mr-2">[{slot.index}]</span>
                <span className="text-white">{slot.name}</span>
              </div>
              <span className={`text-[10px] px-2 py-0.5 rounded font-bold ${
                slot.index === 0 ? 'bg-gray-800 text-gray-400' : 'bg-cyber-cyan/20 text-cyber-cyan'
              }`}>
                {slot.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
