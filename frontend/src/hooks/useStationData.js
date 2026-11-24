import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';

const REFRESH_INTERVAL = 30000;
const REQUEST_TIMEOUT = 45000;
const initialState = { data: null, error: '', loading: true };

export function useStationData(station) {
  const [arrivals, setArrivals] = useState(initialState);
  const [alerts, setAlerts] = useState(initialState);
  const refreshRef = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    let refreshTimer;
    let pending = false;

    async function load(path, field, setState, selectRows) {
      setState(previous => ({ ...previous, error: '', loading: true }));
      const timeout = AbortSignal.timeout(REQUEST_TIMEOUT);
      const signal = AbortSignal.any([controller.signal, timeout]);
      try {
        const data = await api(path, { signal });
        if (!Array.isArray(data?.[field])) {
          throw new Error(`Invalid ${field} response.`);
        }
        if (!controller.signal.aborted) {
          setState({ data: { ...data, [field]: selectRows(data[field]) }, error: '', loading: false });
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          const message = timeout.aborted ? 'Request timed out. Please retry.' : error.message;
          setState(previous => ({ ...previous, error: message, loading: false }));
        }
      }
    }

    async function refresh() {
      if (pending || controller.signal.aborted) return;
      clearTimeout(refreshTimer);
      pending = true;
      await Promise.all([
        load(`/stations/${encodeURIComponent(station.id)}/arrivals`, 'arrivals', setArrivals, rows => rows),
        load('/alerts', 'alerts', setAlerts, rows => rows.filter(alert =>
          alert.route_ids.length === 0 || alert.route_ids.some(route => station.routes.includes(route))
        )),
      ]);
      pending = false;
      if (!controller.signal.aborted) refreshTimer = setTimeout(refresh, REFRESH_INTERVAL);
    }

    refreshRef.current = refresh;
    refresh();
    return () => {
      clearTimeout(refreshTimer);
      controller.abort();
      refreshRef.current = null;
    };
  }, [station]);

  return { arrivals, alerts, refresh: () => refreshRef.current?.() };
}
