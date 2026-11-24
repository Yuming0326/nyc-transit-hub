import React from 'react';

function formatUpdatedAt(value) {
  if (!value) return 'time unavailable';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'time unavailable' : date.toLocaleTimeString();
}

function formatMinutes(value) {
  const arrivalTime = new Date(value).getTime();
  return Number.isNaN(arrivalTime) ? 'Time unavailable' : `${Math.max(0, Math.ceil((arrivalTime - Date.now()) / 60000))} min`;
}

export default function ArrivalBoard({ data, error, loading, refreshing, refresh }) {
  const now = Date.now();
  const arrivals = (data?.arrivals ?? []).filter(arrival => !(Date.parse(arrival.arrival_time) <= now));
  const sourceLabel = data?.source === 'mta' ? 'Live MTA data' : data?.source === 'demo' ? 'Demo data' : '';
  const sourceClass = data?.source === 'mta' ? 'source-live' : 'source-demo';
  return <section className="panel"><div className="panel-heading"><h2>Upcoming trains</h2><button className="refresh-button" type="button" onClick={refresh} disabled={loading || refreshing}>{(loading || refreshing) && data ? 'Refreshing…' : 'Refresh'}</button></div>
    {loading && !data && <p role="status">Loading arrivals…</p>}
    {loading && data && <p role="status" className="muted">Refreshing arrivals…</p>}
    {error && <p role="alert" className="error">{error} {data && 'Showing predictions from the last successful response.'}</p>}
    {data && <>{sourceLabel && <p className={`muted source-label ${sourceClass}`}><span className="status-dot" aria-hidden="true" />{sourceLabel} · updated {formatUpdatedAt(data.updated_at)}</p>}
    <div className="arrivals">{arrivals.map(arrival => <div className="arrival" key={arrival.id}><span className="route">{arrival.route_id}</span><div><strong>{arrival.destination}</strong><small>{arrival.direction}</small></div><b>{formatMinutes(arrival.arrival_time)}</b></div>)}</div>
    {!arrivals.length && <p>{error ? 'No upcoming arrivals in the last successful response.' : 'No upcoming arrivals.'}</p>}</>}
  </section>;
}
