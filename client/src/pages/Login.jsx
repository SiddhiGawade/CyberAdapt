/* ──────────────────────────────────────────────────────────────
   Page: Login
   ────────────────────────────────────────────────────────────── */
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Shield, Lock, Mail, AlertTriangle, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const navigate   = useNavigate();

  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-cyber-bg bg-grid flex items-center justify-center p-4">
      <div className="w-full max-w-md animate-fade-in">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-cyber-card border border-cyber-cyan/20 shadow-glow-cyan mb-4">
            <Shield className="w-8 h-8 text-cyber-cyan" strokeWidth={1.5} />
          </div>
          <h1 className="text-2xl font-bold tracking-[0.15em] text-white text-glow-cyan">
            CYBERADAPT
          </h1>
          <p className="text-xs text-cyber-text tracking-widest uppercase mt-1">
            Secure Operations Console
          </p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="bg-cyber-card rounded-2xl border border-cyber-border p-8 space-y-6"
        >
          <h2 className="text-lg font-semibold text-white text-center">Authenticate</h2>

          {error && (
            <div className="flex items-center gap-2 px-4 py-3 bg-cyber-red/10 border border-cyber-red/20 rounded-lg text-sm text-cyber-red animate-slide-in">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-cyber-dim" />
              <input
                id="login-email"
                type="email"
                placeholder="admin@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-cyber pl-10"
                required
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-cyber-dim" />
              <input
                id="login-password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-cyber pl-10"
                required
              />
            </div>
          </div>

          <button type="submit" disabled={loading} className="btn-cyber w-full flex items-center justify-center gap-2">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Lock className="w-4 h-4" />}
            {loading ? 'Authenticating…' : 'Login'}
          </button>

          <p className="text-xs text-center text-cyber-dim">
            No account?{' '}
            <Link to="/register" className="text-cyber-cyan hover:underline">
              Register your organisation
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
