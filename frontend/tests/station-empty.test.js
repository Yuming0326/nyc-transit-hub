import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { transformWithEsbuild } from 'vite';

async function component(name) {
  const source = await readFile(new URL(`../src/components/${name}.jsx`, import.meta.url), 'utf8');
  const { code } = await transformWithEsbuild(source.replace(/^import .*;\n/gm, '').replace('export default function', 'function'), `${name}.jsx`, { loader: 'jsx' });
  const context = vm.createContext({ React });
  vm.runInContext(code + `\nglobalThis.component = ${name};`, context);
  return context.component;
}
const ArrivalBoard = await component('ArrivalBoard');
const ServiceAlerts = await component('ServiceAlerts');
const hookSource = (await readFile(new URL('../src/hooks/useStationData.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace('export function', 'function');

function mount() {
  const state = [], refs = [];
  let cursor = 0, refCursor = 0, cleanup, started = false, result;
  const calls = [];
  const response = { kind: 'empty' };
  const context = vm.createContext({ AbortController, AbortSignal, Date,
    setTimeout: () => 1, clearTimeout() {},
    useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
    useRef(initial) { const i = refCursor++; return refs[i] ??= { current: initial }; },
    useEffect(fn) { if (!started) { started = true; cleanup = fn(); } },
    api: async path => {
      calls.push(path);
      if (response.kind === 'error') throw new Error('Controlled upstream failure');
      const arrivals = response.kind === 'populated' ? [{ id: 'mock-train', route_id: 'R', destination: 'Controlled destination', direction: 'North', arrival_time: '2099-01-01T00:00:00Z' }] : [];
      const alerts = response.kind === 'populated' ? [{ id: 'mock-alert', header: 'Controlled alert', description: 'Fixture only', route_ids: ['R'] }] : [];
      // Resolve a successful HTTP 200 JSON response, as the API wrapper does.
      return new Response(JSON.stringify(path === '/alerts' ? { source: 'mta', alerts } : { source: 'mta', updated_at: '2026-11-24T17:00:00Z', arrivals }), { status: 200 }).json();
    },
  });
  vm.runInContext(hookSource + '\nglobalThis.hook = useStationData;', context);
  function render() { cursor = refCursor = 0; result = context.hook({ id: 'R20', routes: ['R'] }); return result; }
  async function settle() { for (let i = 0; i < 4; i++) { await new Promise(resolve => setImmediate(resolve)); render(); } }
  const markup = () => renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement(ArrivalBoard, { ...result.arrivals, lastRefreshed: result.lastRefreshed, refresh: result.refresh }),
    React.createElement(ServiceAlerts, result.alerts)));
  render();
  return { response, calls, settle, markup, refresh: async () => { await result.refresh(); await settle(); }, dispose: () => cleanup?.() };
}

function assertEmpty(page) {
  const html = page.markup();
  assert.match(html, /No upcoming arrivals\./);
  assert.match(html, /No active service alerts for these routes\./);
  assert.doesNotMatch(html, /role="alert"|class="error"|Controlled destination|Controlled alert|Loading arrivals|Loading service alerts/);
}

test('HTTP 200 empty arrivals and alerts render empty messages without errors on initial load', async () => {
  const page = mount();
  try { await page.settle(); assertEmpty(page); assert.deepEqual(page.calls, ['/stations/R20/arrivals', '/alerts']); }
  finally { page.dispose(); }
});

test('successful empty refresh clears populated results and recovers from errors', async () => {
  const page = mount();
  try {
    await page.settle();
    page.response.kind = 'populated'; await page.refresh();
    assert.match(page.markup(), /Controlled destination/); assert.match(page.markup(), /Controlled alert/);
    page.response.kind = 'empty'; await page.refresh(); assertEmpty(page);
    page.response.kind = 'error'; await page.refresh(); assert.match(page.markup(), /role="alert"/);
    page.response.kind = 'empty'; await page.refresh(); assertEmpty(page);
  } finally { page.dispose(); }
});
