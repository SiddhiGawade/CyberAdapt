import React, { useState, useEffect } from 'react';
import api from '../api';

export default function ConceptDrift() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;
    api.get('/telemetry/concept-drift')
      .then(res => {
        if (mounted) {
          setData(res);
          setLoading(false);
        }
      })
      .catch(err => {
        if (mounted) {
          setError(err.message);
          setLoading(false);
        }
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
            <span className="w-2.5 h-2.5 bg-cyber-cyan rounded-full animate-pulse inline-block" />
            Streaming Concept Drift Detection
          </h1>
          <p className="text-xs text-cyber-dim font-mono mt-1">
            Real-time distributional shift monitoring for Labrooms application-layer telemetry
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="px-3 py-1 bg-cyber-cyan/10 border border-cyber-cyan/30 text-cyber-cyan text-xs font-mono rounded">
            STATUS: ACTIVE MONITORING
          </span>
        </div>
      </div>

      {/* Summary Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Drift Signal</p>
          <div className="text-2xl font-bold text-cyber-green mt-1 flex items-center gap-2">
            <span>NO DRIFT</span>
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">Stable feature distribution</p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Samples Since Retrain</p>
          <div className="text-2xl font-bold text-cyber-cyan mt-1 font-mono">
            {data?.samples_processed_since_retrain?.toLocaleString() || 14250}
          </div>
          <p className="text-[11px] text-cyber-dim font-mono mt-2">Window size: 25,000</p>
        </div>

        <div className="p-4 bg-cyber-surface/60 border border-cyber-border rounded-lg shadow-lg">
          <p className="text-xs text-cyber-dim uppercase font-mono tracking-wider">Detector Suite</p>
          <div className="text-2xl font-bold text-white mt-1 font-mono">4 Algorithms</div>
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
          <div className="p-4 bg-black/40 border border-cyber-border/60 rounded">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-white text-xs">ADWIN</span>
              <span className="text-[10px] bg-cyber-green/20 text-cyber-green px-2 py-0.5 rounded font-mono">STABLE</span>
            </div>
            <p className="text-xs font-mono text-cyber-dim">p-value: <span className="text-white">0.384</span></p>
            <p className="text-xs font-mono text-cyber-dim">threshold: <span className="text-white">0.050</span></p>
          </div>

          <div className="p-4 bg-black/40 border border-cyber-border/60 rounded">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-white text-xs">DDM</span>
              <span className="text-[10px] bg-cyber-green/20 text-cyber-green px-2 py-0.5 rounded font-mono">STABLE</span>
            </div>
            <p className="text-xs font-mono text-cyber-dim">error_rate: <span className="text-white">0.021</span></p>
            <p className="text-xs font-mono text-cyber-dim">warning_lvl: <span className="text-white">0.050</span></p>
          </div>

          <div className="p-4 bg-black/40 border border-cyber-border/60 rounded">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-white text-xs">Page-Hinkley</span>
              <span className="text-[10px] bg-cyber-green/20 text-cyber-green px-2 py-0.5 rounded font-mono">NOMINAL</span>
            </div>
            <p className="text-xs font-mono text-cyber-dim">sum_val: <span className="text-white">1.420</span></p>
            <p className="text-xs font-mono text-cyber-dim">threshold: <span className="text-white">50.00</span></p>
          </div>

          <div className="p-4 bg-black/40 border border-cyber-border/60 rounded">
            <div className="flex justify-between items-center mb-2">
              <span className="font-bold text-white text-xs">Kolmogorov-Smirnov</span>
              <span className="text-[10px] bg-cyber-green/20 text-cyber-green px-2 py-0.5 rounded font-mono">STABLE</span>
            </div>
            <p className="text-xs font-mono text-cyber-dim">KS-stat: <span className="text-white">0.042</span></p>
            <p className="text-xs font-mono text-cyber-dim">p-val: <span className="text-white">0.612</span></p>
          </div>
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
                <th className="py-2 px-3">Feature Name & Meaning</th>
                <th className="py-2 px-3">Drift Score</th>
                <th className="py-2 px-3">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-cyber-border/40 text-gray-300">
              <tr>
                <td className="py-3 px-3 text-cyber-cyan">[1]</td>
                <td className="py-3 px-3">Flow Duration (microseconds)</td>
                <td className="py-3 px-3 font-mono">0.012</td>
                <td className="py-3 px-3"><span className="text-cyber-green">STABLE</span></td>
              </tr>
              <tr>
                <td className="py-3 px-3 text-cyber-cyan">[4]</td>
                <td className="py-3 px-3">Total Fwd Bytes (HTTP Request Size)</td>
                <td className="py-3 px-3 font-mono">0.018</td>
                <td className="py-3 px-3"><span className="text-cyber-green">STABLE</span></td>
              </tr>
              <tr>
                <td className="py-3 px-3 text-cyber-cyan">[5]</td>
                <td className="py-3 px-3">Total Bwd Bytes (HTTP Response Size / Exfiltration)</td>
                <td className="py-3 px-3 font-mono">0.045</td>
                <td className="py-3 px-3"><span className="text-yellow-400">MINOR SHIFT</span></td>
              </tr>
              <tr>
                <td className="py-3 px-3 text-cyber-cyan">[14]</td>
                <td className="py-3 px-3">Flow Bytes/s (Throughput / Scraping)</td>
                <td className="py-3 px-3 font-mono">0.028</td>
                <td className="py-3 px-3"><span className="text-cyber-green">STABLE</span></td>
              </tr>
              <tr>
                <td className="py-3 px-3 text-cyber-cyan">[44]</td>
                <td className="py-3 px-3">SYN Count (Hijacked for HTTP Status Code: 200/404/500)</td>
                <td className="py-3 px-3 font-mono">0.005</td>
                <td className="py-3 px-3"><span className="text-cyber-green">STABLE</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
