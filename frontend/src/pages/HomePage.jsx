import React, { useEffect, useState } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import StationSearch from '../components/StationSearch';
import StationPage from './StationPage';
import { api } from '../services/api';
import { auth, logIn, logOut } from '../services/firebase';

export default function HomePage() {
  const [stations, setStations] = useState([]);
  const [selected, setSelected] = useState('R20');
  const [query, setQuery] = useState('');
  const [transitMode, setTransitMode] = useState('loading');
  const [stationsLoading, setStationsLoading] = useState(true);
  const [stationsError, setStationsError] = useState('');
  const [error, setError] = useState('');
  const [user, setUser] = useState(null);
  const [favorites, setFavorites] = useState([]);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api('/health')
      .then(data => { if (active) setTransitMode(data.transit_mode === 'live' ? 'live' : 'demo'); })
      .catch(() => { if (active) setTransitMode('offline'); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setStationsLoading(true);
    setStationsError('');
    api('/stations')
      .then(data => {
        if (!active) return;
        if (!Array.isArray(data?.stations)) throw new Error('Invalid stations response');
        const nextStations = data.stations
          .filter(station => station && station.id && station.name)
          .map(station => ({ ...station, routes: Array.isArray(station.routes) ? station.routes : [] }));
        setStations(nextStations);
        setSelected(current => nextStations.some(station => station.id === current) ? current : (nextStations[0]?.id || ''));
      })
      .catch(error => { if (active) setStationsError(error.message); })
      .finally(() => { if (active) setStationsLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => auth ? onAuthStateChanged(auth, setUser) : undefined, []);
  useEffect(() => {
    let active = true;
    setFavorites([]);
    if (user) api('/favorites').then(data => { if (active) setFavorites(Array.isArray(data?.favorites) ? data.favorites : []); }).catch(error => { if (active) setError(error.message); });
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
    const data = await api('/favorites'); setFavorites(Array.isArray(data?.favorites) ? data.favorites : []);
  }
  const filtered = stations.filter(item => `${item.name} ${item.routes.join(' ')}`.toLowerCase().includes(query.toLowerCase()));
  const status = transitMode === 'live'
    ? { label: 'Live MTA data', className: 'status-live' }
    : transitMode === 'demo'
      ? { label: 'Demo data', className: 'status-demo' }
      : transitMode === 'offline'
        ? { label: 'Backend unavailable', className: 'status-offline' }
        : { label: 'Checking backend…', className: 'status-pending' };
  const footerCatalog = transitMode === 'live'
    ? 'Live MTA station catalog'
    : transitMode === 'demo'
      ? 'Demo station catalog'
      : transitMode === 'offline'
        ? 'Backend status unavailable'
        : 'Checking transit data source…';
  return <><header><div><p className="eyebrow">YOUR CITY, CONNECTED</p><h1>NYC Transit Hub<span className="dot">.</span></h1><p>Find your station. Plan your next move.</p></div>{auth && <button disabled={busy} onClick={() => act(user ? logOut : logIn)}>{user ? 'Sign out' : 'Sign in with Google'}</button>}</header>
    <div className={`notice status-banner ${status.className}`} role="status"><span className="status-dot" aria-hidden="true" /><strong>{status.label}</strong></div>
    {error && <p className="error" role="alert">{error}</p>}
    <main><aside>{stationsLoading ? <section className="panel"><p role="status">Loading stations…</p></section> : stationsError ? <section className="panel"><p className="error" role="alert">Unable to load stations: {stationsError}</p></section> : <StationSearch query={query} onChange={setQuery} stations={filtered} selected={selected} onSelect={setSelected} />}
    <section className="panel"><h2>Saved stations</h2>{!auth ? <p>Add Firebase configuration to enable sign-in and favorites.</p> : !user ? <p>Sign in to save your stations.</p> : <>{favorites.map(item => <button className="favorite" key={item.station_id} onClick={() => setSelected(item.station_id)}>{stations.find(station => station.id === item.station_id)?.name || item.station_id}</button>)}{!favorites.length && <p>No saved stations yet.</p>}{station && <button disabled={busy} onClick={() => act(toggleFavorite)}>{saved ? 'Remove current station' : 'Save current station'}</button>}</>}</section></aside>
    {stationsLoading ? <p role="status">Loading station dashboard…</p> : stationsError ? <p className="error" role="alert">Station data unavailable. Check the Flask server.</p> : station ? <StationPage station={station} /> : <p role="status">No stations are available.</p>}</main><footer>NYC Transit Hub · Student project · {footerCatalog}</footer></>;
}
