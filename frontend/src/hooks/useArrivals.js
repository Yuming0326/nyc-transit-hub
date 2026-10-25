import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
export function useArrivals(stationId) {
  const [state, setState] = useState({ data: null, error: '', loading: true });
  const active = useRef(false);
  const requestId = useRef(0);
  const refresh = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setState(previous => ({ ...previous, error: '', loading: true }));
    try {
      const data = await api(`/stations/${encodeURIComponent(stationId)}/arrivals`);
      if (active.current && currentRequest === requestId.current) {
        setState({ data, error: '', loading: false });
      }
    } catch (error) {
      if (active.current && currentRequest === requestId.current) {
        setState(previous => ({ ...previous, error: error.message, loading: false }));
      }
    }
  }, [stationId]);
  useEffect(() => {
    active.current = true;
    let cancelled = false;
    let timer;
    setState({ data: null, error: '', loading: true });
    async function poll() {
      await refresh();
      if (!cancelled) timer = setTimeout(poll, 30000);
    }
    poll();
    return () => {
      cancelled = true;
      active.current = false;
      requestId.current += 1;
      clearTimeout(timer);
    };
  }, [refresh]);
  return { ...state, refresh };
}
