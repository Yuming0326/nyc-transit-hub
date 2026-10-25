import { useEffect, useState } from 'react';
import { api } from '../services/api';
export function useArrivals(stationId) {
  const [state, setState] = useState({ data: null, error: '', loading: true });
  useEffect(() => {
    let active = true;
    let timer;
    setState({ data: null, error: '', loading: true });
    async function load() {
      try {
        const data = await api(`/stations/${encodeURIComponent(stationId)}/arrivals`);
        if (active) setState({ data, error: '', loading: false });
      } catch (error) {
        if (active) setState(previous => ({ ...previous, error: error.message, loading: false }));
      } finally {
        if (active) timer = setTimeout(load, 30000);
      }
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [stationId]);
  return state;
}
