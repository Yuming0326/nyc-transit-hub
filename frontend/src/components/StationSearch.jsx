import React from 'react';

export default function StationSearch({ query, onChange, stations, selected, onSelect }) {
  return <section className="panel"><h2>Find a station</h2>
    <label htmlFor="station-search">Station name or subway line</label>
    <input id="station-search" value={query} onChange={event => onChange(event.target.value)} placeholder="Search stations…" />
    <div className="stations">{stations.map(station => <button key={station.id} aria-pressed={selected === station.id} className={selected === station.id ? 'station selected' : 'station'} onClick={() => onSelect(station.id)}><strong>{station.name}</strong><span>{station.routes.join(' · ')}</span></button>)}</div>
    {!stations.length && <p>No stations match your search.</p>}
  </section>;
}
