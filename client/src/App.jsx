/* ──────────────────────────────────────────────────────────────
   App — Root Layout + Client-Side Routing
   ────────────────────────────────────────────────────────────── */
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import Sidebar from './components/Sidebar';

import Login       from './pages/Login';
import Register    from './pages/Register';
import Overview    from './pages/Overview';
import LiveTraffic from './pages/LiveTraffic';
import SensorSetup from './pages/SensorSetup';

/* ── Placeholder pages for nav items without full impl ── */
function PlaceholderPage({ title }) {
  return (
    <div className="flex items-center justify-center h-full animate-fade-in">
      <div className="text-center space-y-3">
        <h2 className="text-lg font-bold tracking-[0.15em] text-white uppercase">{title}</h2>
        <p className="text-sm text-cyber-dim font-mono">Module under development</p>
        <div className="w-24 h-1 mx-auto bg-gradient-to-r from-transparent via-cyber-cyan/40 to-transparent rounded-full" />
      </div>
    </div>
  );
}

/* ── Auth Guard ── */
function ProtectedRoute() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-cyber-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="flex min-h-screen bg-cyber-bg bg-grid">
      <Sidebar />
      <main className="flex-1 ml-64 p-6 overflow-y-auto h-screen">
        <Outlet />
      </main>
    </div>
  );
}

/* ── Public Route (redirect to / if already logged in) ── */
function PublicRoute() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-cyber-bg flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-cyber-cyan/30 border-t-cyber-cyan rounded-full animate-spin" />
      </div>
    );
  }

  if (user) return <Navigate to="/" replace />;

  return <Outlet />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public routes */}
          <Route element={<PublicRoute />}>
            <Route path="/login"    element={<Login />} />
            <Route path="/register" element={<Register />} />
          </Route>

          {/* Protected dashboard routes */}
          <Route element={<ProtectedRoute />}>
            <Route path="/"              element={<Overview />} />
            <Route path="/live-traffic"  element={<LiveTraffic />} />
            <Route path="/sensor-setup"  element={<SensorSetup />} />
            <Route path="/concept-drift" element={<PlaceholderPage title="Concept Drift Detection" />} />
            <Route path="/adaptation"    element={<PlaceholderPage title="Model Adaptation" />} />
            <Route path="/explain"       element={<PlaceholderPage title="Explainability Engine" />} />
            <Route path="/evaluation"    element={<PlaceholderPage title="Model Evaluation" />} />
          </Route>

          {/* Catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
