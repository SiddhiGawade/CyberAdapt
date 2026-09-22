/* ──────────────────────────────────────────────────────────────
   Sidebar — SOC Navigation Panel
   ────────────────────────────────────────────────────────────── */
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Shield,
  LayoutDashboard,
  Radio,
  GitBranch,
  Brain,
  Search,
  BarChart3,
  Cpu,
  LogOut,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const NAV_ITEMS = [
  { to: '/',             label: 'Overview',         icon: LayoutDashboard },
  { to: '/live-traffic', label: 'Live Traffic',     icon: Radio },
  { to: '/concept-drift',label: 'Concept Drift',    icon: GitBranch },
  { to: '/adaptation',   label: 'Model Adaptation', icon: Brain },
  { to: '/explain',      label: 'Explainability',   icon: Search },
  { to: '/evaluation',   label: 'Evaluation',       icon: BarChart3 },
  { to: '/sensor-setup', label: 'Sensor Setup',     icon: Cpu },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-cyber-card border-r border-cyber-border flex flex-col z-40">
      {/* ── Brand ── */}
      <div className="px-5 py-6 border-b border-cyber-border">
        <div className="flex items-center gap-3 mb-3">
          <div className="relative">
            <Shield className="w-8 h-8 text-cyber-cyan" strokeWidth={1.5} />
            <div className="absolute inset-0 w-8 h-8 bg-cyber-cyan/20 blur-lg rounded-full" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-[0.2em] text-white">CYBERADAPT</h1>
            <p className="text-[9px] tracking-[0.15em] text-cyber-text uppercase leading-tight">
              Adaptive Cyber Threat Intelligence
            </p>
          </div>
        </div>
        {/* Status badge */}
        <div className="flex items-center gap-2 mt-3 px-3 py-1.5 bg-cyber-green/5 border border-cyber-green/20 rounded-full w-fit">
          <span className="w-2 h-2 rounded-full bg-cyber-green status-dot-pulse" />
          <span className="text-[10px] font-mono font-medium text-cyber-green tracking-widest">
            SYSTEM ONLINE
          </span>
        </div>
      </div>

      {/* ── Navigation ── */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group
              ${isActive
                ? 'bg-cyber-cyan/10 text-cyber-cyan glow-border-active'
                : 'text-cyber-text hover:text-white hover:bg-white/5'
              }`
            }
          >
            <Icon className="w-4 h-4 shrink-0 group-hover:drop-shadow-[0_0_6px_rgba(0,229,255,0.5)]" strokeWidth={1.5} />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* ── User / Logout ── */}
      <div className="px-4 py-4 border-t border-cyber-border">
        {user && (
          <div className="mb-3">
            <p className="text-xs font-mono text-cyber-cyan truncate">{user.domain}</p>
            <p className="text-[10px] text-cyber-dim truncate">{user.name}</p>
          </div>
        )}
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 text-sm text-cyber-dim hover:text-cyber-red transition-colors w-full"
        >
          <LogOut className="w-4 h-4" strokeWidth={1.5} />
          <span>Disconnect</span>
        </button>
      </div>
    </aside>
  );
}
