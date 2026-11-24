import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
import { transformWithEsbuild } from 'vite';

const source = await readFile(new URL('../src/pages/HomePage.jsx', import.meta.url), 'utf8');
const { code } = await transformWithEsbuild(source.replace(/^import .*;\n/gm, '').replace('export default function', 'function'), 'HomePage.jsx', { loader: 'jsx' });
const stations = [{ id: 'R20', name: 'Union Square', routes: ['R'] }, { id: 'R21', name: 'NYU', routes: ['R'] }];

function mount(store, options = {}) {
  const state = [], deps = [], cleanup = [], effects = [];
  let cursor = 0, tree, authChanged;
  const user = { uid: 'test-user' };
  const React = { createElement: (type, props, ...children) => ({ type, props: props || {}, children }), Fragment: 'fragment' };
  const api = async (path, request = {}) => {
    if (path === '/health') return { transit_mode: 'live' };
    if (path === '/stations') return { stations };
    if (options.fail) throw new Error('Favorites unavailable');
    if (request.method === 'POST') { store.add(JSON.parse(request.body).station_id); return {}; }
    if (request.method === 'DELETE') { store.delete(decodeURIComponent(path.split('/').at(-1))); return {}; }
    return { favorites: [...store].map(station_id => ({ station_id })) };
  };
  const context = vm.createContext({ React, api, AbortController, AbortSignal,
    auth: { currentUser: user }, logIn() {}, logOut() {},
    StationSearch: 'StationSearch', StationPage: 'StationPage',
    onAuthStateChanged: (_auth, callback) => { authChanged = callback; callback(user); return () => {}; },
    useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], value => { state[i] = typeof value === 'function' ? value(state[i]) : value; }]; },
    useEffect(fn, next) { const i = cursor++; if (!deps[i] || next.some((value, index) => value !== deps[i][index])) { deps[i] = next; effects.push(() => { cleanup[i]?.(); cleanup[i] = fn(); }); } },
  });
  vm.runInContext(code + '\nglobalThis.render = HomePage;', context);
  function render() { cursor = 0; tree = context.render(); while (effects.length) effects.shift()(); return tree; }
  const flush = async () => { for (let i = 0; i < 4; i++) { await new Promise(resolve => setImmediate(resolve)); render(); } };
  const nodes = () => {
    const output = [];
    function walk(node) { if (Array.isArray(node)) node.forEach(walk); else if (node && typeof node === 'object') { output.push(node); node.children.forEach(walk); } }
    walk(tree); return output;
  };
  const text = node => Array.isArray(node) ? node.map(text).join('') : node && typeof node === 'object' ? text(node.children) : node == null || node === false ? '' : String(node);
  const button = label => nodes().find(node => node.type === 'button' && text(node) === label);
  render();
  return { flush, nodes, text, button, signOut: () => { context.auth.currentUser = null; authChanged(null); }, dispose: () => cleanup.forEach(fn => fn?.()) };
}

test('favorites are discoverable, save, restore after remount, select and remove', async () => {
  const store = new Set();
  const first = mount(store);
  await first.flush();
  assert.equal(first.button('Save current station').props.disabled, false);
  const order = first.nodes();
  assert.ok(order.indexOf(first.button('Save current station')) < order.findIndex(node => node.type === 'StationSearch'));
  await first.button('Save current station').props.onClick();
  await first.flush();
  assert.ok(first.button('Remove current station'));
  assert.ok(store.has('R20'));
  first.dispose();
  const reloaded = mount(store);
  await reloaded.flush();
  assert.ok(reloaded.button('Remove current station'));
  reloaded.nodes().find(node => node.type === 'StationSearch').props.onSelect('R21');
  await reloaded.flush();
  assert.ok(reloaded.button('Save current station'));
  reloaded.button('Union Square').props.onClick();
  await reloaded.flush();
  assert.equal(reloaded.nodes().find(node => node.type === 'StationPage').props.station.id, 'R20');
  assert.equal(reloaded.button('Union Square').props['aria-pressed'], true);
  await reloaded.button('Remove current station').props.onClick();
  await reloaded.flush();
  assert.equal(store.size, 0);
  assert.ok(reloaded.button('Save current station'));
  reloaded.dispose();
  const afterRemoval = mount(store);
  await afterRemoval.flush();
  assert.equal(afterRemoval.button('Union Square'), undefined);
  afterRemoval.dispose();
});

test('favorites errors are visible and retry reloads server state', async () => {
  const options = { fail: true };
  const page = mount(new Set(['R20']), options);
  await page.flush();
  assert.ok(page.nodes().some(node => node.props.role === 'alert' && page.text(node).includes('Favorites unavailable')));
  assert.equal(page.button('Save current station').props.disabled, true);
  options.fail = false;
  page.button('Retry saved stations').props.onClick();
  await page.flush();
  assert.ok(page.button('Remove current station'));
  options.fail = true;
  await page.button('Remove current station').props.onClick();
  await page.flush();
  assert.ok(page.button('Union Square'), 'failed delete retains saved station');
  page.signOut(); await page.flush();
  assert.equal(page.button('Union Square'), undefined);
  page.dispose();
});
