import { useEffect, useState } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import StationSearch from '../components/StationSearch';
import StationPage from './StationPage';
import { api } from '../services/api';
import { auth, logIn, logOut } from '../services/firebase';
export default function HomePage() {
  const [stations, setStations] = useState([]);
  const [selected, setSelected] = useState('R20');
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [user, setUser] = useState(null);
  const [favorites, setFavorites] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api('/stations').then(data => setStations(data.stations)).catch(error => setError(error.message)); }, []);
  useEffect(() => auth ? onAuthStateChanged(auth, setUser) : undefined, []);
  useEffect(() => {
    let active = true;
    setFavorites([]);
    if (user) api('/favorites').then(data => { if (active) setFavorites(data.favorites); }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [user]);
  async function act(action) {
    setBusy(true); setError('');
    try { await action(); } catch (error) { setError(error.message); } finally { setBusy(false); }
  }
  const station = stations.find(item => item.id === selected);
  const saved = favorites.some(item => item.station_id === selected);
  async function toggleFavorite() {
    await api(saved ? `/favorites/${selected}` : '/favorites', saved ? { method: 'DELETE' } : { method: 'POST', body: JSON.stringify({ station_id: selected }) });
    const data = await api('/favorites'); setFavorites(data.favorites);
  }
  const filtered = stations.filter(item => `${item.name} ${item.routes.join(' ')}`.toLowerCase().includes(query.toLowerCase()));
  return <><header><div><p className="eyebrow">YOUR CITY, CONNECTED</p><h1>NYC Transit Hub<span className="dot">.</span></h1><p>Find your station. Plan your next move.</p></div>{auth && <button disabled={busy} onClick={() => act(user ? logOut : logIn)}>{user ? 'Sign out' : 'Sign in with Google'}</button>}</header>
    <div className="notice"><strong>Demo mode</strong> · All arrivals and alerts are fictional sample data. Live MTA feeds are not connected.</div>
    {error && <p className="error" role="alert">{error}</p>}
    <main><aside><StationSearch query={query} onChange={setQuery} stations={filtered} selected={selected} onSelect={setSelected} />
    <section className="panel"><h2>Saved stations</h2>{!auth ? <p>Add Firebase configuration to enable sign-in and favorites.</p> : !user ? <p>Sign in to save your stations.</p> : <>{favorites.map(item => <button className="favorite" key={item.station_id} onClick={() => setSelected(item.station_id)}>{stations.find(station => station.id === item.station_id)?.name || item.station_id}</button>)}{!favorites.length && <p>No saved stations yet.</p>}{station && <button disabled={busy} onClick={() => act(toggleFavorite)}>{saved ? 'Remove current station' : 'Save current station'}</button>}</>}</section></aside>
    {station ? <StationPage station={station} /> : <p role="status">{error ? 'Station data unavailable. Check the Flask server.' : 'Loading stations…'}</p>}</main><footer>NYC Transit Hub · Student project · Sample station catalog</footer></>;
}
