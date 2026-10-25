import { useEffect, useState } from 'react';
import ArrivalBoard from '../components/ArrivalBoard';
import ServiceAlerts from '../components/ServiceAlerts';
import { useArrivals } from '../hooks/useArrivals';
import { api } from '../services/api';
export default function StationPage({ station }) {
  const arrivals = useArrivals(station.id);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setAlerts([]); setError('');
    api(`/alerts?route_id=${encodeURIComponent(station.routes[0])}`).then(data => { if (active) setAlerts(data.alerts); }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [station.id]);
  return <div><h2 className="station-title">{station.name}</h2><ArrivalBoard {...arrivals} /><ServiceAlerts alerts={alerts} error={error} /></div>;
}
