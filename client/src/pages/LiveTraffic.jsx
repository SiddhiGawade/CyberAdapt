/* ──────────────────────────────────────────────────────────────
   Page: Live Traffic
   ────────────────────────────────────────────────────────────── */
import GlowCard from '../components/GlowCard';
import LiveTrafficTable from '../components/LiveTrafficTable';

export default function LiveTraffic() {
  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h1 className="text-xl font-bold tracking-[0.15em] text-white uppercase">
          Live Traffic Monitor
        </h1>
        <p className="text-sm text-cyber-text mt-1">
          Streaming network flow telemetry from deployed sensors
        </p>
      </div>
      <GlowCard className="p-6">
        <LiveTrafficTable />
      </GlowCard>
    </div>
  );
}
