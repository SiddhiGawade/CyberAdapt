/* ──────────────────────────────────────────────────────────────
   GlowCard — Reusable panel with glowing border
   ────────────────────────────────────────────────────────────── */
export default function GlowCard({ children, className = '', glow = 'cyan', ...props }) {
  const glowMap = {
    cyan:  'border-cyber-cyan/15 hover:border-cyber-cyan/30 hover:shadow-glow-cyan',
    red:   'border-cyber-red/15 hover:border-cyber-red/30 hover:shadow-glow-red',
    green: 'border-cyber-green/15 hover:border-cyber-green/30 hover:shadow-glow-green',
    none:  'border-cyber-border',
  };

  return (
    <div
      className={`bg-cyber-card rounded-xl border transition-all duration-500 ${glowMap[glow] || glowMap.cyan} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
