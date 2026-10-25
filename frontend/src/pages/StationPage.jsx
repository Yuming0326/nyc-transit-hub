import React, { useCallback, useEffect, useRef, useState } from 'react';
import ArrivalBoard from '../components/ArrivalBoard';
import ServiceAlerts from '../components/ServiceAlerts';
import { useArrivals } from '../hooks/useArrivals';
import { api } from '../services/api';
export default function StationPage({ station }) {
  const arrivals = useArrivals(station.id);
  const [alertsState, setAlertsState] = useState({ data: null, error: '', loading: true });
  const alertsActive = useRef(false);
  const alertsRequestId = useRef(0);
  const routeId = Array.isArray(station.routes) ? (station.routes[0] || '') : '';
  const loadAlerts = useCallback(async () => {
    const currentRequest = ++alertsRequestId.current;
    setAlertsState(previous => ({ ...previous, error: '', loading: true }));
    try {
      const data = await api(`/alerts?route_id=${encodeURIComponent(routeId)}`);
      if (alertsActive.current && currentRequest === alertsRequestId.current) {
        setAlertsState({ data, error: '', loading: false });
      }
    } catch (error) {
      if (alertsActive.current && currentRequest === alertsRequestId.current) {
        setAlertsState(previous => ({ ...previous, error: error.message, loading: false }));
      }
    }
  }, [routeId]);
  useEffect(() => {
    alertsActive.current = true;
    setAlertsState({ data: null, error: '', loading: true });
    loadAlerts();
    return () => {
      alertsActive.current = false;
      alertsRequestId.current += 1;
    };
  }, [loadAlerts]);
  const refreshDashboard = useCallback(async () => {
    await Promise.all([arrivals.refresh(), loadAlerts()]);
  }, [arrivals.refresh, loadAlerts]);
  return <div><h2 className="station-title">{station.name}</h2><ArrivalBoard {...arrivals} refreshing={alertsState.loading} refresh={refreshDashboard} /><ServiceAlerts {...alertsState} /></div>;
}
