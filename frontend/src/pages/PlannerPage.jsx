import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import ResourceState from '../components/ResourceState';
import { useI18n } from '../i18n';

function localInputValue(date = new Date()) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function TargetPicker({ id, label, value, onChange }) {
  const [query, setQuery] = useState('');
  const [rows, setRows] = useState([]);
  const [state, setState] = useState({ loading: false, error: '' });
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setState({ loading: true, error: '' });
      try {
        const data = await api(`/stations?search=${encodeURIComponent(query.trim())}`, { signal: controller.signal });
        setRows(Array.isArray(data?.stations) ? data.stations : []);
        setState({ loading: false, error: '' });
      } catch (error) { if (!controller.signal.aborted) setState({ loading: false, error: error.message }); }
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query]);
  return <div className="target-picker"><label htmlFor={id}>{label}</label><input id={id} value={query} onChange={event => setQuery(event.target.value)} placeholder="Search subway stations" />
    {value && <p className="selection-chip">Selected: <strong>{value.name}</strong> <button type="button" aria-label={`Clear ${label}`} onClick={() => onChange(null)}>×</button></p>}
    {state.loading && <p role="status" className="muted">Searching…</p>}{state.error && <p role="alert" className="error">{state.error}</p>}
    {!value && <div className="choice-list compact">{rows.slice(0, 8).map(station => <button type="button" key={station.id} onClick={() => { onChange({ type: 'station', mode: 'subway', id: station.id, name: station.name }); setQuery(station.name); }}>{station.name}<span>{station.routes?.join(' · ')}</span></button>)}</div>}
  </div>;
}

export default function PlannerPage() {
  const { t } = useI18n();
  const [origin, setOrigin] = useState(null);
  const [destination, setDestination] = useState(null);
  const [departure, setDeparture] = useState(localInputValue());
  const [state, setState] = useState({ data: null, loading: false, error: '' });
  async function plan(event) {
    event.preventDefault();
    if (!origin || !destination) { setState({ data: null, loading: false, error: 'Select both an origin and destination.' }); return; }
    setState(previous => ({ ...previous, loading: true, error: '' }));
    try {
      const data = await api('/journeys', { method: 'POST', body: JSON.stringify({ origin: { type: origin.type, mode: origin.mode, id: origin.id }, destination: { type: destination.type, mode: destination.mode, id: destination.id }, departure_time: new Date(departure).toISOString(), modes: ['subway'], optimization: 'fewest_transfers' }) });
      setState({ data, loading: false, error: '' });
    } catch (error) { setState(previous => ({ ...previous, loading: false, error: error.message })); }
  }
  const journeys = state.data?.journeys || [];
  return <div className="feature-grid"><form className="panel" onSubmit={plan}><h2>{t('planJourney')}</h2><p className="muted">Schedule-based subway journeys. Live rerouting is not provided.</p>
    <TargetPicker id="origin" label={t('origin')} value={origin} onChange={setOrigin} /><TargetPicker id="destination" label={t('destination')} value={destination} onChange={setDestination} />
    <label htmlFor="departure">{t('departure')}</label><input id="departure" type="datetime-local" value={departure} onChange={event => setDeparture(event.target.value)} required />
    <button className="primary" disabled={state.loading} type="submit">{state.loading ? 'Planning…' : t('findJourneys')}</button>
  </form><section className="panel"><h2>{t('journeyOptions')}</h2><ResourceState {...state} empty={Boolean(state.data) && !journeys.length} emptyMessage={state.data?.no_path_reason ? `No journey found: ${state.data.no_path_reason.replaceAll('_', ' ')}.` : 'No journey was found in the supported time window.'}>
    {!state.data && !state.loading && !state.error && <p>Choose an origin, destination and departure time.</p>}
    {journeys.map((journey, index) => <article className="journey" key={journey.id}><h3>Option {index + 1}</h3><p><strong>{new Date(journey.departure_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} – {new Date(journey.arrival_time).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</strong> · {journey.transfers} transfer{journey.transfers === 1 ? '' : 's'}</p>
      <ol>{journey.legs.map((leg, legIndex) => <li key={`${journey.id}-${legIndex}`}><span className="route">{leg.mode === 'walk' ? 'W' : leg.route_id}</span><div><strong>{leg.mode === 'walk' ? 'Walk transfer' : `Take ${leg.route_id}`}</strong><small>{leg.from.id} → {leg.to.id}</small></div></li>)}</ol>
    </article>)}
  </ResourceState></section></div>;
}
