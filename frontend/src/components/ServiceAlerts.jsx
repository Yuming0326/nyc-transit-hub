import React from 'react';

export default function ServiceAlerts({ data, error, loading }) {
  const alerts = Array.isArray(data?.alerts) ? data.alerts : [];
  const sourceLabel = data?.source === 'mta' ? 'Live MTA data' : data?.source === 'demo' ? 'Demo data' : '';
  const sourceClass = data?.source === 'mta' ? 'source-live' : 'source-demo';
  return <section className="panel"><h2>Service alerts</h2>
    {loading && !data && <p role="status">Loading service alerts…</p>}
    {loading && data && <p role="status" className="muted">Refreshing service alerts…</p>}
    {error && <p role="alert" className="error">{error} {data && 'Showing the last successful response.'}</p>}
    {sourceLabel && <p className={`muted source-label ${sourceClass}`}><span className="status-dot" aria-hidden="true" />{sourceLabel}</p>}
    {alerts.map((alert, index) => {
      const routeIds = Array.isArray(alert?.route_ids) ? alert.route_ids : [];
      return <article className="alert" key={alert?.id || `${alert?.header || 'alert'}-${index}`}><strong>{alert?.header || 'Service alert'}</strong><p>{alert?.description || 'No description available.'}</p><small>Routes: {routeIds.length ? routeIds.join(', ') : 'No route specified'}</small></article>;
    })}
    {data && !alerts.length && <p>{error ? 'No alerts in the last successful response.' : 'No active service alerts for these routes.'}</p>}
  </section>;
}
