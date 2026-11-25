import React, { useMemo } from 'react';

function collectCoordinates(geometry) {
  const points = [];
  for (const feature of geometry?.features || []) {
    const coordinates = feature?.geometry?.coordinates || [];
    const lines = feature?.geometry?.type === 'MultiLineString' ? coordinates : [coordinates];
    for (const line of lines) for (const point of line) if (Array.isArray(point) && point.length >= 2) points.push(point);
  }
  return points;
}

export default function TransitMap({ data, selectedId, onSelect }) {
  const model = useMemo(() => {
    const entities = [...(data?.stations || []), ...(data?.stops || [])];
    const coordinates = [...collectCoordinates(data?.geometry), ...entities.map(item => [item.longitude, item.latitude])]
      .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));
    if (!coordinates.length) return null;
    const lngs = coordinates.map(point => point[0]);
    const lats = coordinates.map(point => point[1]);
    const bounds = { minLng: Math.min(...lngs), maxLng: Math.max(...lngs), minLat: Math.min(...lats), maxLat: Math.max(...lats) };
    const project = ([lng, lat]) => [24 + ((lng - bounds.minLng) / (bounds.maxLng - bounds.minLng || 1)) * 752, 476 - ((lat - bounds.minLat) / (bounds.maxLat - bounds.minLat || 1)) * 452];
    const lines = (data?.geometry?.features || []).flatMap(feature => {
      const raw = feature?.geometry?.coordinates || [];
      const groups = feature?.geometry?.type === 'MultiLineString' ? raw : [raw];
      return groups.map((line, index) => ({ id: `${feature?.properties?.id || 'route'}-${index}`, points: line.map(project).map(point => point.join(',')).join(' ') }));
    });
    return { entities, lines, project };
  }, [data]);
  if (!model) return <p>No mapped geometry or coordinates are available.</p>;
  return <div className="map-frame">
    <svg viewBox="0 0 800 500" role="img" aria-label="Transit route map">
      <rect width="800" height="500" className="map-background" />
      {model.lines.map(line => <polyline key={line.id} points={line.points} className="map-line" />)}
      {model.entities.map(entity => {
        if (!Number.isFinite(entity.longitude) || !Number.isFinite(entity.latitude)) return null;
        const [x, y] = model.project([entity.longitude, entity.latitude]);
        return <g key={entity.id} className="map-point" role="button" tabIndex="0" aria-label={entity.name} aria-pressed={selectedId === entity.id} onClick={() => onSelect?.(entity)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect?.(entity); } }}>
          <circle cx={x} cy={y} r={selectedId === entity.id ? 9 : 6} className={selectedId === entity.id ? 'map-selected' : ''} />
          {selectedId === entity.id && <text x={x + 12} y={y - 10}>{entity.name}</text>}
        </g>;
      })}
    </svg>
  </div>;
}
