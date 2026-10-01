import React, { useMemo } from 'react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend
} from 'recharts';

export default function TrafficSpikeChart({ flows }) {
  // Aggregate telemetry flows into 10-second time windows
  const chartData = useMemo(() => {
    if (!flows || flows.length === 0) return [];

    const bucketMap = {};

    flows.forEach((flow) => {
      if (!flow.receivedAt) return;
      const date = new Date(flow.receivedAt);
      // Round down to 10-second interval
      const sec = Math.floor(date.getSeconds() / 10) * 10;
      date.setSeconds(sec, 0);

      const timeKey = date.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });

      if (!bucketMap[timeKey]) {
        bucketMap[timeKey] = {
          time: timeKey,
          timestamp: date.getTime(),
          totalFlows: 0,
          normalFlows: 0,
          attackSurge: 0,
        };
      }

      bucketMap[timeKey].totalFlows += 1;
      const isAttack = flow.threatLabel && flow.threatLabel !== 'Normal Traffic';
      if (isAttack) {
        bucketMap[timeKey].attackSurge += 1;
      } else {
        bucketMap[timeKey].normalFlows += 1;
      }
    });

    // Sort chronologically by timestamp
    return Object.values(bucketMap).sort((a, b) => a.timestamp - b.timestamp).slice(-15);
  }, [flows]);

  return (
    <div className="w-full space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold uppercase tracking-wider text-cyber-cyan font-mono flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-cyber-cyan animate-ping" />
            Live Telemetry Flow Rate & Attack Spike Timeline
          </h3>
          <p className="text-xs text-cyber-dim font-mono mt-0.5">
            Chronological 10s time series — shows baseline low traffic and attack packet surges
          </p>
        </div>
        <div className="text-xs font-mono text-cyber-dim">
          Time Windows: <span className="text-white font-bold">{chartData.length}</span>
        </div>
      </div>

      <div className="h-64 w-full bg-black/40 border border-cyber-border/60 rounded-lg p-3">
        {chartData.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-cyber-dim font-mono text-xs space-y-2">
            <div className="w-6 h-6 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
            <span>Streaming real telemetry data from sensor...</span>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData} margin={{ top: 10, right: 20, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00f3ff" stopOpacity={0.4}/>
                  <stop offset="95%" stopColor="#00f3ff" stopOpacity={0.0}/>
                </linearGradient>
                <linearGradient id="colorSurge" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ff0055" stopOpacity={0.8}/>
                  <stop offset="95%" stopColor="#ff0055" stopOpacity={0.1}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f293d" />
              <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10 }} />
              <YAxis stroke="#64748b" tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0b0f19', borderColor: '#00f3ff', borderRadius: '6px', fontSize: '12px' }}
                itemStyle={{ color: '#fff' }}
              />
              <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace' }} />
              <Area type="monotone" dataKey="totalFlows" name="Total Ingested Flows" stroke="#00f3ff" fillOpacity={1} fill="url(#colorTotal)" strokeWidth={2} isAnimationActive={false} />
              <Area type="monotone" dataKey="attackSurge" name="Detected Attack Surges" stroke="#ff0055" fillOpacity={1} fill="url(#colorSurge)" strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
