import React, { useState } from 'react';
import { useApiResource } from '../hooks/useApiResource';
import ResourceState from '../components/ResourceState';
import { useI18n } from '../i18n';

export default function ServicesPage({ station }) {
  const { t } = useI18n();
  const [mode, setMode] = useState('subway');
  const status = useApiResource(`/service-status?mode=${mode}`);
  const equipment = useApiResource(station ? `/stations/${encodeURIComponent(station.id)}/equipment` : null, { enabled: Boolean(station) });
  const statuses = status.data?.statuses || [];
  const items = equipment.data?.equipment || [];
  return <div className="feature-grid"><section className="panel"><div className="panel-heading"><h2>{t('serviceStatus')}</h2><button type="button" onClick={status.reload} disabled={status.loading}>{t('refresh')}</button></div>
    <div className="segmented">{['subway', 'bus'].map(value => <button type="button" key={value} aria-pressed={mode === value} onClick={() => setMode(value)}>{t(value)}</button>)}</div>
    <ResourceState {...status} onRetry={status.reload} empty={Boolean(status.data) && !statuses.length} emptyMessage="No route status records are available.">{statuses.map(item => <article className={`status-card status-${item.status}`} key={item.route_id}><span className="route">{item.route_id}</span><div><strong>{item.status === 'normal' ? 'Normal service' : item.status === 'disruption' ? 'Disruption' : t('unknown')}</strong><small>Basis: {item.basis?.replaceAll('_', ' ') || 'not supplied'}</small></div></article>)}</ResourceState>
    {status.data && <p className="muted">{t('source')}: {status.data.source || t('unknown')} · {t('updated')}: {status.data.updated_at ? new Date(status.data.updated_at).toLocaleString() : t('unknown')}</p>}
  </section><section className="panel"><div className="panel-heading"><h2>{t('equipment')}</h2><button type="button" onClick={equipment.reload} disabled={!station || equipment.loading}>{t('refresh')}</button></div>
    <p>{station ? <><strong>{station.name}</strong><br /></> : null}<span className="muted">Coverage: {equipment.data?.coverage || 'unknown'}. Unknown does not mean accessible.</span></p>
    {!station ? <p>Select a station on the dashboard first.</p> : <ResourceState {...equipment} onRetry={equipment.reload} empty={Boolean(equipment.data) && !items.length} emptyMessage={equipment.data?.coverage === 'complete' ? 'The source reports no equipment at this station.' : 'No equipment records are available; accessibility is unknown.'}>{items.map(item => <article className="equipment" key={item.id}><strong>{item.type === 'elevator' ? 'Elevator' : 'Escalator'} · {item.status.replaceAll('_', ' ')}</strong><p>{item.description}</p>{item.return_to_service_at && <small>Estimated return: {new Date(item.return_to_service_at).toLocaleString()}</small>}</article>)}</ResourceState>}
  </section></div>;
}
