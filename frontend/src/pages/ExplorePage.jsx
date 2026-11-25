import React, { useMemo, useState } from 'react';
import ResourceState from '../components/ResourceState';
import TransitMap from '../components/TransitMap';
import { useApiResource } from '../hooks/useApiResource';
import { useI18n } from '../i18n';

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'Time unavailable' : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export default function ExplorePage() {
  const { t } = useI18n();
  const [mode, setMode] = useState('subway');
  const [routeId, setRouteId] = useState('');
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const routesPath = `/${mode}/routes${query.trim() ? `?search=${encodeURIComponent(query.trim())}` : ''}`;
  const routes = useApiResource(routesPath);
  const detail = useApiResource(routeId ? `/${mode}/routes/${encodeURIComponent(routeId)}` : null, { enabled: Boolean(routeId) });
  const map = useApiResource(`/map?mode=${mode}${routeId ? `&route_id=${encodeURIComponent(routeId)}` : ''}`);
  const vehicles = useApiResource(mode === 'bus' && routeId ? `/bus/vehicles?route_id=${encodeURIComponent(routeId)}` : null, { enabled: mode === 'bus' && Boolean(routeId) });
  const arrivalsPath = selected ? (mode === 'bus' ? `/bus/stops/${encodeURIComponent(selected.id)}/arrivals${routeId ? `?route_id=${encodeURIComponent(routeId)}` : ''}` : `/stations/${encodeURIComponent(selected.id)}/arrivals`) : null;
  const arrivals = useApiResource(arrivalsPath, { enabled: Boolean(arrivalsPath) });
  const routeRows = Array.isArray(routes.data?.routes) ? routes.data.routes : [];
  const entities = mode === 'bus' ? detail.data?.stops : detail.data?.stations;
  const entityRows = Array.isArray(entities) ? entities : [];
  const mapData = useMemo(() => {
    if (!map.data) return null;
    if (mode !== 'bus' || !Array.isArray(vehicles.data?.vehicles)) return map.data;
    return { ...map.data, stops: [...(map.data.stops || []), ...vehicles.data.vehicles.map(vehicle => ({ ...vehicle, id: `vehicle-${vehicle.id}`, name: `Vehicle ${vehicle.id}` }))] };
  }, [map.data, mode, vehicles.data]);
  function changeMode(next) { setMode(next); setRouteId(''); setSelected(null); setQuery(''); }
  return <div className="feature-grid">
    <section className="panel controls-panel"><h2>{t('exploreTransit')}</h2>
      <div className="segmented" aria-label="Transit mode">{['subway', 'bus'].map(value => <button type="button" key={value} aria-pressed={mode === value} onClick={() => changeMode(value)}>{t(value)}</button>)}</div>
      <label htmlFor="route-search">{t('searchRoutes')}</label><input id="route-search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t('searchRoutesHint')} />
      <ResourceState {...routes} onRetry={routes.reload} empty={!routes.loading && !routeRows.length} emptyMessage={t('noRoutes')}>
        <div className="choice-list">{routeRows.map(route => <button type="button" key={route.id} className={routeId === route.id ? 'selected' : ''} aria-pressed={routeId === route.id} onClick={() => { setRouteId(route.id); setSelected(null); }}><strong>{route.short_name || route.id}</strong><span>{route.name}</span></button>)}</div>
      </ResourceState>
      {routeId && <ResourceState {...detail} onRetry={detail.reload} empty={!detail.loading && !entityRows.length} emptyMessage="No stations or stops are listed for this route.">
        <h3>{t('stopsStations')}</h3><div className="choice-list compact">{entityRows.map(entity => <button type="button" key={entity.id} aria-pressed={selected?.id === entity.id} className={selected?.id === entity.id ? 'selected' : ''} onClick={() => setSelected(entity)}>{entity.name}</button>)}</div>
      </ResourceState>}
    </section>
    <div>
      <section className="panel"><div className="panel-heading"><h2>{t('interactiveMap')}</h2><button type="button" onClick={map.reload} disabled={map.loading}>{t('refreshMap')}</button></div>
        <ResourceState {...map} onRetry={map.reload}><TransitMap data={mapData} selectedId={selected?.id} onSelect={item => setSelected(item.id.startsWith('vehicle-') ? selected : item)} /></ResourceState>
        {map.data && <p className="muted">Official geometry · {map.data.updated_at ? `updated ${formatTime(map.data.updated_at)}` : 'source time unavailable'}{mode === 'bus' && vehicles.error ? ` · Vehicle positions unavailable: ${vehicles.error}` : ''}</p>}
      </section>
      {selected && <section className="panel"><h2>{selected.name}</h2><p className="muted">{selected.id}</p>
        <ResourceState {...arrivals} onRetry={arrivals.reload} empty={!arrivals.loading && !(arrivals.data?.arrivals || []).length} emptyMessage="No upcoming live arrivals were reported.">
          <div className="arrivals">{(arrivals.data?.arrivals || []).map(item => <div className="arrival" key={item.id}><span className="route">{item.route_id}</span><div><strong>{item.destination || 'Destination unavailable'}</strong><small>{item.direction || item.direction_id || 'Direction unavailable'}</small></div><b>{item.arrival_time ? formatTime(item.arrival_time) : 'ETA unavailable'}</b></div>)}</div>
        </ResourceState>
      </section>}
    </div>
  </div>;
}
