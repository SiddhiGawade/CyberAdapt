/* ──────────────────────────────────────────────────────────────
   API Helper — thin fetch wrapper with JWT injection
   ────────────────────────────────────────────────────────────── */
const API_BASE = '/api';

async function request(endpoint, options = {}) {
  const token = localStorage.getItem('ca_token');

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    err.status = res.status;
    err.data = data;
    throw err;
  }

  return data;
}

export const api = {
  get:  (url) => request(url),
  post: (url, body) => request(url, { method: 'POST', body: JSON.stringify(body) }),
};

export default api;
