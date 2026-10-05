const search = document.querySelector('#search');
const direction = document.querySelector('#direction');
const status = document.querySelector('#status');
const body = document.querySelector('#stocks');
const refresh = document.querySelector('#refresh');
const summary = document.querySelector('#summary');
let report = null;
const labels = {selected: '入选', rejected: '不满足', unknown: '无法判断', pass: '满足', fail: '不满足'};
const kindLabels = {history: '历史日线', minutes: '一分钟成交量', financial: '正式财报', forecasts: '正式业绩预告', funds: '当日主力资金', quote: '当前行情', calendar: '交易日历（指数交易日）'};
function node(tag, text, className = '') {
  const result = document.createElement(tag);
  result.textContent = text;
  result.className = className;
  return result;
}
function displayTime(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value + '（日期）';
  const stamp = Date.parse(value);
  return Number.isFinite(stamp) ? new Date(stamp).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) + '（北京时间）' : '未提供';
}
function link(url, text) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return node('span', text);
    const a = node('a', text);
    a.href = parsed.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  } catch { return node('span', text); }
}
function expired(row) {
  const evaluated = Date.parse(row.evaluatedAt);
  const quote = Date.parse(row.quoteAt);
  const age = Date.now() - Math.min(evaluated, quote);
  return !Number.isFinite(age) || age < 0 || age > 180000;
}
function effectiveStatus(row) {
  if (expired(row) || row.checks.some(c => c.status === 'unknown')) return 'unknown';
  return row.checks.every(c => c.status === 'pass') ? 'selected' : 'rejected';
}
function render() {
  if (!report) return;
  const selected = report.stocks.filter(s => effectiveStatus(s) === 'selected').length;
  const unknown = report.stocks.filter(s => effectiveStatus(s) === 'unknown').length;
  summary.replaceChildren(node('h2', report.complete ? '已完成指定范围扫描' : '无法判断：扫描未完成或范围不完整'));
  summary.append(node('p', `范围：${report.scope} · 已处理 ${report.scannedCount} / ${report.universeCount ?? '未知'} 只 · 当前有效入选 ${selected} 只 · 无法判断 ${unknown} 只`));
  summary.append(node('p', `结果生成：${displayTime(report.generatedAt)}；逐股行情时间见下方。`));
  if (!report.complete) summary.append(node('p', '扫描未完成不能解释为市场上没有符合条件的股票。', 'warning'));
  for (const message of report.errors) summary.append(node('p', message, 'warning'));
  const query = search.value.trim().toLowerCase();
  const matches = report.stocks.filter(s => (s.symbol.includes(query) || s.name.toLowerCase().includes(query)) &&
    (direction.value === 'all' || effectiveStatus(s) === direction.value));
  body.replaceChildren();
  for (const stock of matches) {
    const card = node('article', '', 'stock-card');
    const state = effectiveStatus(stock);
    card.append(node('h2', `${stock.symbol} ${stock.name} · ${labels[state]}`, state));
    card.append(node('p', `行情时间：${displayTime(stock.quoteAt)} · 判断时间：${displayTime(stock.evaluatedAt)}`));
    if (expired(stock)) card.append(node('p', '行情已过期或缺少行情时间，无法判断当前是否入选。以下为扫描时逐项记录。', 'warning'));
    const list = node('ul', '');
    for (const check of stock.checks) list.append(node('li', `${labels[check.status]} · ${check.label}：${check.reason}`, check.status));
    card.append(list);
    const details = node('details', '');
    details.append(node('summary', '查看数据来源与采集问题'));
    for (const source of stock.sources) {
      const line = node('p', `${kindLabels[source.kind] || source.kind} · ${source.status === 'available' ? '已获取' : '不可用'} · `);
      line.append(link(source.url, source.name));
      line.append(node('span', `；数据时间 ${displayTime(source.dataAt)}；采集 ${displayTime(source.fetchedAt)}`));
      details.append(line);
    }
    for (const error of stock.errors) details.append(node('p', `${kindLabels[error.kind] || error.kind}：${error.message}`, 'warning'));
    card.append(details);
    body.append(card);
  }
  status.textContent = matches.length ? `显示 ${matches.length} 条结果；数据缺失或过期均不入选。` :
    (report.stocks.length ? '没有符合当前显示条件的结果。' : '尚无可判断的真实股票结果，请查看扫描状态和接口问题。');
}
async function loadCapabilities() {
  const list = document.querySelector('#capabilities');
  try {
    const response = await fetch('./capabilities.json', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    document.querySelector('#probe-time').textContent = `检测时间：${displayTime(data.checkedAt)}`;
    list.replaceChildren();
    for (const check of data.checks) {
      const item = node('li', `${kindLabels[check.kind]}：${check.status === 'reachable' ? '样本请求通过' : '尚未确认可获取'}；${check.message} · `);
      item.append(link(check.source, '接口来源'));
      if (check.historicalSource) item.append(node('span', ' · '), link(check.historicalSource, '资金日线来源（不能替代盘中数据）'));
      list.append(item);
    }
  } catch { list.replaceChildren(node('li', '接口检测报告不可用，不能确认数据接口可用。')); }
}
async function load() {
  refresh.disabled = true;
  status.textContent = '正在读取扫描结果…';
  try {
    const response = await fetch('./results.json', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (data.schemaVersion !== 2 || data.dataMode !== 'real' || !Array.isArray(data.stocks) ||
        !Array.isArray(data.errors) || !data.stocks.every(s => typeof s.symbol === 'string' && typeof s.name === 'string' &&
        ['selected', 'rejected', 'unknown'].includes(s.status) && Array.isArray(s.checks) && s.checks.length === 5 &&
        s.checks.every(c => ['pass', 'fail', 'unknown'].includes(c.status)) && Array.isArray(s.sources) && Array.isArray(s.errors))) throw new Error();
    report = data;
    render();
  } catch {
    report = null;
    summary.replaceChildren(node('h2', '无法判断：真实扫描结果加载失败'));
    body.replaceChildren();
    status.textContent = '真实扫描结果加载失败或格式无效，无法判断。不会使用演示数据。';
  } finally { refresh.disabled = false; }
  await loadCapabilities();
}
search.addEventListener('input', render);
direction.addEventListener('change', render);
refresh.addEventListener('click', load);
async function loadVersion() {
  try {
    const response = await fetch('./build.json', {cache: 'no-store'});
    if (!response.ok) return;
    const data = await response.json();
    if (typeof data.commit === 'string' && /^[0-9a-f]{40}$/.test(data.commit)) {
      const element = document.querySelector('#build-version');
      if (element) element.textContent = `发布版本：${data.commit.slice(0, 7)} · 真实筛选前端 v2`;
    }
  } catch { /* Local development has no published build metadata. */ }
}
setInterval(render, 30000);
loadVersion();
load();
