import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import ResourceState from '../components/ResourceState';
import { useI18n } from '../i18n';

async function targetId(target) {
  const bytes = new TextEncoder().encode(JSON.stringify([target.mode, target.type, target.id]));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

export default function NotificationsPage({ user, station }) {
  const { t } = useI18n();
  const [state, setState] = useState({ data: null, loading: Boolean(user), error: '' });
  const [subscription, setSubscription] = useState({ enabled: false, loading: false, error: '' });
  const evaluating = useRef(false);
  const load = useCallback(async () => {
    if (!user) return;
    setState(previous => ({ ...previous, loading: true, error: '' }));
    try {
      const data = await api('/notifications?limit=50');
      setState({ data, loading: false, error: '' });
    } catch (error) { setState(previous => ({ ...previous, loading: false, error: error.message })); }
  }, [user]);
  const evaluate = useCallback(async () => {
    if (!user || evaluating.current) return;
    evaluating.current = true;
    try { await api('/notifications/evaluate', { method: 'POST', body: '{}' }); await load(); }
    catch (error) { setState(previous => ({ ...previous, loading: false, error: error.message })); }
    finally { evaluating.current = false; }
  }, [load, user]);
  useEffect(() => {
    if (!user) { setState({ data: null, loading: false, error: '' }); return undefined; }
    evaluate();
    const timer = setInterval(evaluate, 30000);
    return () => clearInterval(timer);
  }, [evaluate, user]);
  useEffect(() => {
    if (!user || !station) return undefined;
    let active = true;
    api('/subscriptions?limit=100').then(data => {
      const found = (data.subscriptions || []).find(item => item.target?.mode === 'subway' && item.target?.type === 'station' && item.target?.id === station.id);
      if (active) setSubscription({ enabled: Boolean(found?.enabled), loading: false, error: '' });
    }).catch(error => { if (active) setSubscription({ enabled: false, loading: false, error: error.message }); });
    return () => { active = false; };
  }, [station, user]);
  async function toggleSubscription() {
    const target = { mode: 'subway', type: 'station', id: station.id };
    setSubscription(previous => ({ ...previous, loading: true, error: '' }));
    try {
      const id = await targetId(target);
      const next = !subscription.enabled;
      await api(`/subscriptions/${id}`, { method: 'PUT', body: JSON.stringify({ target, enabled: next }) });
      setSubscription({ enabled: next, loading: false, error: '' });
    } catch (error) { setSubscription(previous => ({ ...previous, loading: false, error: error.message })); }
  }
  async function setRead(notification, read) {
    try {
      await api(`/notifications/${encodeURIComponent(notification.id)}`, { method: 'PATCH', body: JSON.stringify({ read }) });
      setState(previous => ({ ...previous, data: { ...previous.data, notifications: previous.data.notifications.map(item => item.id === notification.id ? { ...item, read } : item), unread_count: previous.data.unread_count + (read ? -1 : 1) } }));
    } catch (error) { setState(previous => ({ ...previous, error: error.message })); }
  }
  if (!user) return <section className="panel"><h2>{t('notifications')}</h2><p>{t('signInNotifications')}</p></section>;
  const rows = state.data?.notifications || [];
  return <div className="feature-grid"><section className="panel"><h2>{t('subscriptions')}</h2>{station ? <><p>{t('selectedStation')}: <strong>{station.name}</strong></p><button type="button" className={subscription.enabled ? '' : 'primary'} onClick={toggleSubscription} disabled={subscription.loading}>{subscription.loading ? 'Updating…' : subscription.enabled ? t('disableAlerts') : t('enableAlerts')}</button>{subscription.error && <p role="alert" className="error">{subscription.error}</p>}</> : <p>Select a station on the dashboard to subscribe.</p>}<p className="muted">Subscriptions are separate from saved items. Notices refresh only while this panel is open.</p></section>
    <section className="panel"><div className="panel-heading"><h2>{t('notifications')} <span className="count-badge" aria-label={`${state.data?.unread_count || 0} unread`}>{state.data?.unread_count || 0}</span></h2><button type="button" onClick={evaluate} disabled={state.loading}>{t('retry')}</button></div><ResourceState {...state} onRetry={evaluate} empty={Boolean(state.data) && !rows.length} emptyMessage={t('noNotifications')}>{rows.map(item => <article className={item.read ? 'notification' : 'notification unread'} key={item.id}><div><strong>{item.title}</strong><p>{item.body}</p><small>{new Date(item.created_at).toLocaleString()}</small></div><button type="button" onClick={() => setRead(item, !item.read)}>{item.read ? 'Mark unread' : 'Mark read'}</button></article>)}</ResourceState></section>
  </div>;
}
