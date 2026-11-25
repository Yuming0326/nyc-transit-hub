import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
const identity = value => value;

export function useApiResource(path, { enabled = true, timeout = 45000, transform = identity } = {}) {
  const [state, setState] = useState({ data: null, error: '', loading: enabled });
  const requestId = useRef(0);
  const load = useCallback(async () => {
    if (!enabled || !path) return;
    const id = ++requestId.current;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort('timeout'), timeout);
    setState(previous => ({ ...previous, error: '', loading: true }));
    try {
      const data = transform(await api(path, { signal: controller.signal }));
      if (id === requestId.current) setState({ data, error: '', loading: false });
    } catch (error) {
      if (id === requestId.current) setState(previous => ({ ...previous, error: controller.signal.reason === 'timeout' ? 'Request timed out. Please retry.' : error.message, loading: false }));
    } finally {
      clearTimeout(timer);
    }
  }, [enabled, path, timeout, transform]);
  useEffect(() => {
    setState({ data: null, error: '', loading: enabled });
    load();
    return () => { requestId.current += 1; };
  }, [enabled, load, path]);
  return { ...state, reload: load };
}
