import React from 'react';
import ArrivalBoard from '../components/ArrivalBoard';
import ServiceAlerts from '../components/ServiceAlerts';
import { useStationData } from '../hooks/useStationData';

export default function StationPage({ station }) {
  const { arrivals, alerts, lastRefreshed, refresh } = useStationData(station);

  return <div>
    <h2 className="station-title">{station.name}</h2>
    <ArrivalBoard {...arrivals} lastRefreshed={lastRefreshed} refreshing={alerts.loading} refresh={refresh} />
    <ServiceAlerts {...alerts} />
  </div>;
}
