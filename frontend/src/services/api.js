import { auth } from './firebase';
const base = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export async function api(path, options = {}) {
  const token = auth?.currentUser ? await auth.currentUser.getIdToken() : null;
  const response = await fetch(`${base}/api${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
  });
  let body;
  try { body = await response.json(); }
  catch { body = {}; }
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}
