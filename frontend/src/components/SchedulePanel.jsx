import React, { useState } from 'react';
import { useApiResource } from '../hooks/useApiResource';
import ResourceState from './ResourceState';

function today() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export default function SchedulePanel({ station }) {
  const [date, setDate] = useState(today());
  const [direction, setDirection] = useState('');
  const [routeId, setRouteId] = useState('');
  const query = new URLSearchParams({ mode: 'subway', date, station_id: station.id });
  if (direction) query.set('direction_id', direction);
  if (routeId) query.set('route_id', routeId);
  const state = useApiResource(`/schedules?${query}`);
  const rows = state.data?.departures || [];
  return <section className="panel"><div className="panel-heading"><div><h2>Scheduled departures</h2><p className="muted">Timetable information—not live predictions.</p></div><button type="button" onClick={state.reload} disabled={state.loading}>Refresh</button></div>
    <div className="inline-controls"><label>Date<input type="date" value={date} onChange={event => setDate(event.target.value)} /></label><label>Route<select value={routeId} onChange={event => setRouteId(event.target.value)}><option value="">All routes</option>{station.routes.map(route => <option key={route} value={route}>{route}</option>)}</select></label><label>Direction<select value={direction} onChange={event => setDirection(event.target.value)}><option value="">Both</option><option value="0">Direction 0</option><option value="1">Direction 1</option></select></label></div>
    <ResourceState {...state} onRetry={state.reload} empty={Boolean(state.data) && !rows.length} emptyMessage="No scheduled departures were found for this service date."><div className="schedule-list">{rows.slice(0, 20).map(item => <div key={item.id}><span className="route">{item.route_id}</span><strong>{item.departure_time ? new Date(item.departure_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : item.service_time}</strong><span>{item.destination || 'Destination unavailable'} · direction {item.direction_id ?? 'unknown'}</span></div>)}</div></ResourceState>
    {state.data && <p className="muted">Service date {state.data.service_date} · {state.data.timezone} · {state.data.source}</p>}
  </section>;
}
