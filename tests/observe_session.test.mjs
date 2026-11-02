import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/observability/front-observer/src/main.js', import.meta.url), 'utf8');
function functionSource(name, next) {
  const start = source.indexOf(`async function ${name}(`);
  const end = next ? source.indexOf(`\nasync function ${next}(`, start) : source.indexOf('\nboot();', start);
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}
function harness({ metricsFail = false, unauthorized = false, rejectLogin = false } = {}) {
  const elements = new Map();
  const context = vm.createContext({
    $: id => {
      if (!elements.has(id)) elements.set(id, { value: '', textContent: '' });
      return elements.get(id);
    },
    TAB_KEY: 'test-session', OBS: '/observability', location: { hash: '#lab' },
    sessionStorage: { getItem: () => '1' },
    initDateFilters() {}, activateView() {},
    requestJSON: async () => { if (rejectLogin) throw new Error('Credenciais inválidas'); },
  });
  vm.runInContext(`
    let authState = 'anonymous';
    let shown = 0;
    function showLogin() { shown++; }
    function startSession() { authState = 'active'; }
    async function loadData() {
      if (${unauthorized}) { authState = 'anonymous'; showLogin(); }
      return ${!metricsFail};
    }
    ${functionSource('submitLogin', 'logout')}
    ${functionSource('boot')}
    globalThis.snapshot = () => ({ authState, shown });
  `, context);
  return context;
}
test('successful login survives a metrics outage', async () => {
  const c = harness({ metricsFail: true });
  await c.submitLogin({ preventDefault() {} });
  assert.equal(c.snapshot().authState, 'active');
  assert.equal(c.snapshot().shown, 0);
});
test('restored session survives a metrics outage', async () => {
  const c = harness({ metricsFail: true });
  await c.boot();
  assert.equal(c.snapshot().authState, 'active');
});
test('unauthorized protected data still closes the session', async () => {
  const c = harness({ unauthorized: true, metricsFail: true });
  await c.submitLogin({ preventDefault() {} });
  assert.equal(c.snapshot().authState, 'anonymous');
  assert.equal(c.snapshot().shown, 1);
});
test('rejected login never opens an authenticated session', async () => {
  const c = harness({ rejectLogin: true });
  await c.submitLogin({ preventDefault() {} });
  assert.equal(c.snapshot().authState, 'anonymous');
  assert.equal(c.$('login-error').textContent, 'Credenciais inválidas');
});
