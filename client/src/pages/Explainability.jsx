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
            Explainability Engine (Model Inputs + Rule Signals)
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            The classifier uses eight selected inputs; HTTP status and response-size rules can override its prediction
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
            52 total slots &rarr; 10 populated Labrooms values &rarr; eight model inputs; flow ID and HTTP status are not model inputs
          </span>
        </div>
      </div>

      {/* Inputs used by the trained classifier */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Model Inputs
        </h2>
        <p className="text-xs text-cyber-dim font-mono">
          The model uses these eight inputs. Slot 5 supplies both backward packet-length proxy columns.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 font-mono text-xs">
          {data?.model_inputs?.map((item) => (
            <div key={item.name} className="p-3 bg-black/40 border border-cyber-border/50 rounded">
              <span className="text-cyber-cyan font-bold">[{item.slot}]</span>
              <span className="text-white ml-2">{item.name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Rules which may override the model prediction */}
      <div className="p-5 bg-cyber-surface/40 border border-cyber-border rounded-lg space-y-4">
        <h2 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono">
          Rule Override Signals (not model inputs)
        </h2>
        <div className="space-y-2 font-mono text-xs">
          {data?.rule_signals?.map((signal) => (
            <div key={signal.slot} className="p-3 bg-black/40 border border-cyber-border/50 rounded">
              <span className="text-cyber-cyan font-bold">[{signal.slot}] {signal.name}</span>
              <span className="text-gray-300 ml-2">{signal.purpose}</span>
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
              <span className="text-[10px] px-2 py-0.5 rounded font-bold bg-cyber-cyan/20 text-cyber-cyan">
                {slot.status}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
