import React, { useEffect, useState } from 'react';
import { onAuthStateChanged } from 'firebase/auth';
import StationSearch from '../components/StationSearch';
import StationPage from './StationPage';
import ExplorePage from './ExplorePage';
import PlannerPage from './PlannerPage';
import ServicesPage from './ServicesPage';
import NotificationsPage from './NotificationsPage';
import { api } from '../services/api';
import { auth, logIn, logOut } from '../services/firebase';
import { useI18n } from '../i18n';

export default function HomePage() {
  const { language, setLanguage, t } = useI18n();
  const [activePage, setActivePage] = useState('dashboard');
  const [stations, setStations] = useState([]);
  const [selected, setSelected] = useState('R20');
  const [query, setQuery] = useState('');
  const [transitMode, setTransitMode] = useState('loading');
  const [stationRequest, setStationRequest] = useState(0);
  const [stationsLoading, setStationsLoading] = useState(true);
  const [stationsError, setStationsError] = useState('');
  const [authError, setAuthError] = useState('');
  const [authLoading, setAuthLoading] = useState(Boolean(auth));
  const [user, setUser] = useState(null);
  const [favorites, setFavorites] = useState([]);
  const [favoritesLoading, setFavoritesLoading] = useState(false);
  const [favoritesError, setFavoritesError] = useState('');
  const [favoritesRequest, setFavoritesRequest] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort('timeout'), 15000);
    setTransitMode('loading');
    api('/health', { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setTransitMode(['live', 'demo'].includes(data?.transit_mode) ? data.transit_mode : 'unknown');
    }).catch(() => { if (!controller.signal.aborted) setTransitMode('unknown'); }).finally(() => clearTimeout(timer));
    return () => { clearTimeout(timer); controller.abort(); };
  }, [stationRequest]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort('timeout'), 15000);
    setStationsLoading(true); setStationsError('');
    api('/stations', { signal: controller.signal }).then(data => {
      if (!Array.isArray(data?.stations)) throw new Error('Invalid stations response.');
      const next = data.stations.filter(item => item?.id && item?.name).map(item => ({ ...item, routes: Array.isArray(item.routes) ? item.routes : [] }));
      setStations(next); setSelected(current => next.some(item => item.id === current) ? current : (next[0]?.id || ''));
    }).catch(error => { if (!controller.signal.aborted) setStationsError(error.message); }).finally(() => { clearTimeout(timer); if (!controller.signal.aborted) setStationsLoading(false); });
    return () => { clearTimeout(timer); controller.abort(); };
  }, [stationRequest]);
  useEffect(() => {
    if (!auth) { setAuthLoading(false); return undefined; }
    return onAuthStateChanged(auth, next => { setUser(next); setAuthLoading(false); }, error => { setAuthError(error.message); setAuthLoading(false); });
  }, []);
  useEffect(() => {
    let active = true;
    setFavorites([]); setFavoritesError(''); setFavoritesLoading(Boolean(user));
    if (user) api('/favorites', { signal: AbortSignal.timeout(45000) }).then(data => {
      if (!Array.isArray(data?.favorites)) throw new Error('Invalid saved stations response.');
      if (active) setFavorites(data.favorites);
    }).catch(error => { if (active) setFavoritesError(error.message); }).finally(() => { if (active) setFavoritesLoading(false); });
    return () => { active = false; };
  }, [user, favoritesRequest]);

  const station = stations.find(item => item.id === selected);
  const saved = favorites.some(item => item.station_id === selected);
  async function toggleFavorite() {
    if (!user || !station || favoritesLoading || favoritesError) return;
    const stationId = station.id; const owner = user.uid;
    setBusy(true); setFavoritesError('');
    try {
      await api(saved ? `/favorites/${encodeURIComponent(stationId)}` : '/favorites', saved ? { method: 'DELETE', signal: AbortSignal.timeout(45000) } : { method: 'POST', body: JSON.stringify({ station_id: stationId }), signal: AbortSignal.timeout(45000) });
      if (auth.currentUser?.uid === owner) setFavorites(previous => saved ? previous.filter(item => item.station_id !== stationId) : [...previous, { station_id: stationId }]);
    } catch (error) { if (auth.currentUser?.uid === owner) setFavoritesError(error.message); } finally { setBusy(false); }
  }
  async function changeAuth() {
    setBusy(true); setAuthError('');
    try { if (user) await logOut(); else await logIn(); }
    catch (error) { setAuthError(error.code === 'auth/popup-closed-by-user' ? 'Sign-in was canceled.' : error.message); }
    finally { setBusy(false); }
  }
  const filtered = stations.filter(item => `${item.name} ${item.routes.join(' ')}`.toLowerCase().includes(query.trim().toLowerCase()));
  const status = { live: [t('liveMode'), 'status-live'], demo: [t('demoMode'), 'status-demo'], unknown: [t('modeUnavailable'), 'status-offline'], loading: [t('checkingBackend'), 'status-pending'] }[transitMode];
  const pages = [['dashboard', t('dashboard')], ['explore', t('explore')], ['planner', t('planner')], ['services', t('services')], ['notifications', t('notifications')]];

  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to content</a><header><div><p className="eyebrow">YOUR CITY, CONNECTED</p><h1>{t('appName')}<span className="dot">.</span></h1><p>{t('tagline')}</p></div><div className="header-actions"><label htmlFor="language">{t('language')}</label><select id="language" value={language} onChange={event => setLanguage(event.target.value)}><option value="en">{t('english')}</option><option value="zh">{t('chinese')}</option></select>{auth && <button disabled={busy || authLoading} onClick={changeAuth}>{user ? t('signOut') : t('signIn')}</button>}</div></header>
    <nav className="main-nav" aria-label="Main navigation">{pages.map(([id, label]) => <button type="button" key={id} aria-current={activePage === id ? 'page' : undefined} onClick={() => setActivePage(id)}>{label}{id === 'notifications' && <span className="nav-dot" aria-hidden="true" />}</button>)}</nav>
    <div className={`notice status-banner ${status[1]}`} role="status"><span className="status-dot" aria-hidden="true" /><strong>{status[0]}</strong></div>
    {authError && <p className="error global-message" role="alert">{authError}</p>}
    <main id="main-content" className={activePage === 'dashboard' ? '' : 'page-main'}>
      {activePage === 'dashboard' && <><aside><section className="panel"><h2>{language === 'zh' ? '收藏的车站' : 'Saved stations'}</h2>{!auth ? <p>Firebase configuration is required for accounts.</p> : authLoading ? <p role="status">{t('loading')}</p> : !user ? <p>{language === 'zh' ? '登录后即可收藏车站。' : 'Sign in to save stations.'}</p> : <>{station && <><p>{language === 'zh' ? '当前车站' : 'Selected station'}: <strong>{station.name}</strong></p><button type="button" disabled={busy || favoritesLoading || Boolean(favoritesError) || !station} onClick={toggleFavorite}>{busy ? 'Updating…' : saved ? (language === 'zh' ? '取消收藏' : 'Remove current station') : (language === 'zh' ? '收藏当前车站' : 'Save current station')}</button></>}{favoritesLoading && <p role="status">{t('loading')}</p>}{favoritesError && <><p className="error" role="alert">{favoritesError}</p><button type="button" onClick={() => setFavoritesRequest(value => value + 1)}>{language === 'zh' ? '重试收藏车站' : 'Retry saved stations'}</button></>}{favorites.map(item => <button type="button" className="favorite" key={item.station_id} aria-pressed={selected === item.station_id} onClick={() => setSelected(item.station_id)} disabled={!stations.some(value => value.id === item.station_id)}>{stations.find(value => value.id === item.station_id)?.name || item.station_id}</button>)}{!favoritesLoading && !favoritesError && !favorites.length && <p>{language === 'zh' ? '还没有收藏车站。' : 'No saved stations yet.'}</p>}</>}</section>
        {stationsLoading ? <section className="panel"><p role="status">{t('loading')}</p></section> : stationsError ? <section className="panel"><p className="error" role="alert">{stationsError}</p><button type="button" onClick={() => setStationRequest(value => value + 1)}>{t('retry')}</button></section> : <StationSearch query={query} onChange={setQuery} stations={filtered} selected={selected} onSelect={setSelected} />}</aside>{!stationsLoading && !stationsError && station ? <StationPage key={station.id} station={station} /> : !stationsLoading && !stationsError ? <p>No stations are available.</p> : null}</>}
      {activePage === 'explore' && <ExplorePage />}{activePage === 'planner' && <PlannerPage />}{activePage === 'services' && <ServicesPage station={station} />}{activePage === 'notifications' && <NotificationsPage user={user} station={station} />}
    </main><footer>NYC Transit Hub · Student project · {t('originalMta')}</footer></div>;
}
