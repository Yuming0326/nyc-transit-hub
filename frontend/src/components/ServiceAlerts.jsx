export default function ServiceAlerts({ alerts, error }) {
  return <section className="panel"><h2>Service alerts</h2>{error && <p role="alert" className="error">{error}</p>}{alerts.map(alert => <article className="alert" key={alert.id}><strong>{alert.header}</strong><p>{alert.description}</p><small>Routes: {alert.route_ids.join(', ')}</small></article>)}{!alerts.length && !error && <p>No alerts for this sample station.</p>}</section>;
}
