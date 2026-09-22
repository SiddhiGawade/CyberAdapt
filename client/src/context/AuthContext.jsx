/* ──────────────────────────────────────────────────────────────
   AuthContext — JWT auth state, login/register/logout handlers
   ────────────────────────────────────────────────────────────── */
import { createContext, useContext, useState, useEffect } from 'react';
import api from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [token, setToken]     = useState(localStorage.getItem('ca_token'));
  const [loading, setLoading] = useState(true);

  /* ── Hydrate session from persisted token ── */
  useEffect(() => {
    if (!token) { setLoading(false); return; }

    api.get('/auth/me')
      .then(({ company }) => setUser(company))
      .catch(() => { localStorage.removeItem('ca_token'); setToken(null); })
      .finally(() => setLoading(false));
  }, [token]);

  /* ── Register ── */
  async function register(name, domain, adminEmail, password) {
    const data = await api.post('/auth/register', { name, domain, adminEmail, password });
    return data;
  }

  /* ── Login ── */
  async function login(email, password) {
    const data = await api.post('/auth/login', { email, password });
    localStorage.setItem('ca_token', data.token);
    setToken(data.token);
    setUser(data.company);
    return data;
  }

  /* ── Logout ── */
  function logout() {
    localStorage.removeItem('ca_token');
    setToken(null);
    setUser(null);
  }

  /* ── Refresh company data (after verification, etc.) ── */
  async function refreshUser() {
    const { company } = await api.get('/auth/me');
    setUser(company);
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
