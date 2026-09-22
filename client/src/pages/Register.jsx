/* ──────────────────────────────────────────────────────────────
   Page: Register
   ────────────────────────────────────────────────────────────── */
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Shield, User, Globe, Mail, Lock, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ name: '', domain: '', adminEmail: '', password: '' });
  const [error, setError]     = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  function update(field) {
    return (e) => setForm((prev) => ({ ...prev, [field]: e.target.value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    setLoading(true);
    try {
      const data = await register(form.name, form.domain, form.adminEmail, form.password);
      setSuccess(`Registered! Your DNS verification token is ready. Redirecting…`);
      setTimeout(() => navigate('/login'), 2500);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  const fields = [
    { key: 'name',       icon: User,  placeholder: 'Organisation Name', type: 'text' },
    { key: 'domain',     icon: Globe, placeholder: 'company.com',       type: 'text' },
    { key: 'adminEmail', icon: Mail,  placeholder: 'admin@company.com', type: 'email' },
    { key: 'password',   icon: Lock,  placeholder: '••••••••',          type: 'password' },
  ];

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
            New Organisation Registration
          </p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          className="bg-cyber-card rounded-2xl border border-cyber-border p-8 space-y-6"
        >
          <h2 className="text-lg font-semibold text-white text-center">Create Account</h2>

          {error && (
            <div className="flex items-center gap-2 px-4 py-3 bg-cyber-red/10 border border-cyber-red/20 rounded-lg text-sm text-cyber-red animate-slide-in">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 px-4 py-3 bg-cyber-green/10 border border-cyber-green/20 rounded-lg text-sm text-cyber-green animate-slide-in">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              {success}
            </div>
          )}

          <div className="space-y-4">
            {fields.map(({ key, icon: Icon, placeholder, type }) => (
              <div key={key} className="relative">
                <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-cyber-dim" />
                <input
                  id={`register-${key}`}
                  type={type}
                  placeholder={placeholder}
                  value={form[key]}
                  onChange={update(key)}
                  className="input-cyber pl-10"
                  required
                />
              </div>
            ))}
          </div>

          <button type="submit" disabled={loading} className="btn-cyber w-full flex items-center justify-center gap-2">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
            {loading ? 'Registering…' : 'Register Organisation'}
          </button>

          <p className="text-xs text-center text-cyber-dim">
            Already registered?{' '}
            <Link to="/login" className="text-cyber-cyan hover:underline">
              Login
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
