/* ──────────────────────────────────────────────────────────────
   Page: Overview (Dashboard)
   ────────────────────────────────────────────────────────────── */
import { useState, useEffect } from 'react';
import { Shield, Activity, Cpu, Key, TrendingUp } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import GlowCard from '../components/GlowCard';
import LiveTrafficTable from '../components/LiveTrafficTable';
import api from '../api';

export default function Overview() {
  const { user } = useAuth();
  const [stats, setStats] = useState({ keys: 0, flows: 0, lastIngest: null });

  useEffect(() => {
    async function load() {
      try {
        const [keysRes, flowsRes] = await Promise.all([
          api.get('/auth/keys'),
          api.get('/telemetry/recent-flows'),
        ]);
        const activeKeys = (keysRes.keys || []).filter((k) => k.isActive);
        const lastIngest = activeKeys.reduce((max, k) => {
          const t = k.lastIngestAt ? new Date(k.lastIngestAt).getTime() : 0;
          return t > max ? t : max;
        }, 0);

        setStats({
          keys: activeKeys.length,
          flows: (flowsRes.flows || []).length,
          lastIngest: lastIngest ? new Date(lastIngest) : null,
        });
      } catch {
        /* non-critical */
      }
    }
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  const kpis = [
    {
      label: 'Domain Status',
      value: user?.isVerified ? 'VERIFIED' : 'PENDING',
      icon: Shield,
      color: user?.isVerified ? 'text-cyber-green' : 'text-cyber-amber',
      glow: user?.isVerified ? 'green' : 'none',
    },
    {
      label: 'Active Sensors',
      value: stats.keys,
      icon: Cpu,
      color: 'text-cyber-cyan',
      glow: 'cyan',
    },
    {
      label: 'Recent Flows',
      value: stats.flows,
      icon: Activity,
      color: 'text-cyber-cyan',
      glow: 'cyan',
    },
    {
      label: 'Last Ingest',
      value: stats.lastIngest
        ? stats.lastIngest.toLocaleTimeString('en-US', { hour12: false })
        : '—',
      icon: TrendingUp,
      color: 'text-cyber-amber',
      glow: 'none',
    },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold tracking-[0.15em] text-white uppercase">
          Operations Overview
        </h1>
        <p className="text-sm text-cyber-text mt-1">
          Real-time system status for <span className="text-cyber-cyan font-mono">{user?.domain}</span>
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {kpis.map(({ label, value, icon: Icon, color, glow }) => (
          <GlowCard key={label} glow={glow} className="p-5">
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] uppercase tracking-widest text-cyber-dim mb-2 font-semibold">{label}</p>
                <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
              </div>
              <div className={`p-2 rounded-lg bg-cyber-card2 ${color}`}>
                <Icon className="w-5 h-5" strokeWidth={1.5} />
              </div>
            </div>
          </GlowCard>
        ))}
      </div>

      {/* Live Flows */}
      <GlowCard className="p-6">
        <LiveTrafficTable />
      </GlowCard>
    </div>
  );
}
