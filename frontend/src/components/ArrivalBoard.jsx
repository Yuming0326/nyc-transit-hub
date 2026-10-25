export default function ArrivalBoard({ data, error, loading }) {
  if (loading) return <p role="status">Loading arrivals…</p>;
  return <section className="panel"><h2>Upcoming trains</h2>
    {error && <p role="alert" className="error">{error} {data && 'Showing the last successful response.'}</p>}
    {data && <><p className="muted">Sample data · updated {new Date(data.updated_at).toLocaleTimeString()}</p>
    <div className="arrivals">{data.arrivals.map(arrival => <div className="arrival" key={arrival.id}><span className="route">{arrival.route_id}</span><div><strong>{arrival.destination}</strong><small>{arrival.direction}</small></div><b>{Math.max(0, Math.ceil((new Date(arrival.arrival_time) - Date.now()) / 60000))} min</b></div>)}</div>
    {!data.arrivals.length && <p>No upcoming arrivals.</p>}</>}
  </section>;
}
