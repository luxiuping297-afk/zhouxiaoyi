// In-memory DOM tests: no artificial market data is written to the website.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const now = Date.parse('2026-09-30T10:05:00+08:00');
class Clock extends Date { static now() { return now; } }
function element(tag = '') {
  return {tag, value: '', textContent: '', children: [], className: '', disabled: false,
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; }, addEventListener() {}};
}
function text(el) { return el.textContent + el.children.map(text).join(' '); }
function stock(overrides = {}) {
  return {symbol: '600000', name: '<script>测试输入</script>', status: 'selected',
    evaluatedAt: new Date(now).toISOString(), quoteAt: new Date(now).toISOString(),
    checks: ['trend', 'gains', 'volume', 'earnings', 'funds'].map(id => ({id, label: id, status: 'pass', reason: '测试证据'})),
    sources: [{kind: 'quote', status: 'available', name: '测试来源', url: 'javascript:alert(1)'}], errors: [], ...overrides};
}
async function run(rows, options = {}) {
  const nodes = {};
  for (const id of ['search', 'direction', 'status', 'stocks', 'refresh', 'summary', 'capabilities', 'probe-time']) nodes['#' + id] = element();
  nodes['#direction'].value = 'all';
  const calls = [];
  const report = {schemaVersion: 2, dataMode: 'real', complete: true, scope: '单元测试范围', scannedCount: rows.length,
    universeCount: rows.length, generatedAt: new Date(now).toISOString(), errors: [], stocks: rows};
  const context = vm.createContext({Date: Clock, URL, setInterval() {},
    document: {querySelector: id => nodes[id], createElement: element},
    fetch: async url => {
      calls.push(url);
      if (options.fail && url.endsWith('results.json')) throw new Error('network failure');
      return {ok: true, json: async () => url.endsWith('results.json') ? report : {checkedAt: new Date(now).toISOString(), checks: []}};
    }});
  vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  return {nodes, context, calls};
}
(async () => {
  let result = await run([stock()]);
  assert.equal(result.nodes['#stocks'].children.length, 1);
  assert.match(text(result.nodes['#summary']), /当前有效入选 1 只/);
  assert.deepEqual(result.calls, ['./results.json', './capabilities.json']);
  assert.match(text(result.nodes['#stocks']), /<script>测试输入<\/script>/);
  const details = result.nodes['#stocks'].children[0].children.at(-1);
  assert.equal(details.children[1].children[0].tag, 'span'); // Non-HTTPS URL is not a link.
  result.nodes['#search'].value = '不存在';
  vm.runInContext('render()', result.context);
  assert.equal(result.nodes['#stocks'].children.length, 0);
  result = await run([stock({quoteAt: new Date(now - 181000).toISOString()})]);
  assert.match(text(result.nodes['#summary']), /当前有效入选 0 只/);
  assert.match(text(result.nodes['#stocks']), /行情已过期/);
  result.nodes['#direction'].value = 'selected';
  vm.runInContext('render()', result.context);
  assert.equal(result.nodes['#stocks'].children.length, 0);
  const failed = stock();
  failed.checks[2].status = 'fail';
  result = await run([failed]);
  assert.match(text(result.nodes['#stocks']), /不满足/);
  assert.match(text(result.nodes['#summary']), /当前有效入选 0 只/);
  const missing = stock();
  missing.checks[4].status = 'unknown';
  result = await run([missing]);
  assert.match(text(result.nodes['#summary']), /无法判断 1 只/);
  result = await run([], {fail: true});
  assert.match(result.nodes['#status'].textContent, /无法判断/);
  assert.equal(result.nodes['#stocks'].children.length, 0);
  console.log('PASS: 前端真实结果加载、搜索、过期隐藏、五项同时满足、缺失/失败状态、安全文本和相对路径');
})().catch(error => { console.error(error); process.exitCode = 1; });
