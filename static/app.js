const search = document.querySelector('#search');
const direction = document.querySelector('#direction');
const status = document.querySelector('#status');
const body = document.querySelector('#stocks');
const refresh = document.querySelector('#refresh');
const summary = document.querySelector('#summary');
let report = null;
let marketCalendar = null;
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

function currentMarket() {
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(new Date(Date.now()));
  const values = Object.fromEntries(parts.map(p => [p.type, p.value]));
  const date = `${values.year}-${values.month}-${values.day}`;
  const year = marketCalendar?.years?.[values.year];
  if (!year) return {state: 'unknown', message: '交易所日历未覆盖当前日期，无法确认交易状态'};
  function isOpenDay(d) {
    const y = marketCalendar.years[d.slice(0, 4)];
    if (!y) return false;
    const weekday = new Date(d + 'T00:00:00Z').getUTCDay();
    return weekday !== 0 && weekday !== 6 && !y.holidays.some(h => h.start <= d && d <= h.end);
  }
  function nearby(direction) {
    const point = new Date(date + 'T00:00:00Z');
    for (let i = 0; i < 21; i++) {
      point.setUTCDate(point.getUTCDate() + direction);
      const d = point.toISOString().slice(0, 10);
      if (isOpenDay(d)) return d;
    }
    return '日历尚未覆盖';
  }
  const result = {supportedScanTime: false, state: 'open', message: '交易时段；继续严格校验全部五项筛选条件', source: year.source, lastTradingDate: nearby(-1), nextTradingDate: nearby(1)};
  const minute = Number(values.hour) * 60 + Number(values.minute);
  result.supportedScanTime = (minute >= 571 && minute <= 690) || (minute >= 781 && minute <= 897);
  if (!isOpenDay(date)) Object.assign(result, {state: 'closed', message: '休市，等待下一交易日'});
  else if (minute < 570) Object.assign(result, {state: 'preopen', message: '尚未开盘，等待今日交易时段'});
  else if (minute > 900) Object.assign(result, {state: 'closed', message: '休市，等待下一交易日', lastTradingDate: date});
  else if (minute > 690 && minute < 780) Object.assign(result, {state: 'break', message: '午间休息，等待下午交易时段'});
  return result;
}
function renderMarket() {
  const area = document.querySelector('#market-state');
  if (!area) return;
  const market = currentMarket();
  area.replaceChildren(node('h2', market.message));
  if (market.source) area.append(link(market.source, '交易所官方休市安排'));
  if (market.state === 'closed') {
    area.append(node('p', `上一交易日：${market.lastTradingDate}；下一交易日：${market.nextTradingDate}（北京时间）。休市期间报价保持在上一交易日属于正常状态，不作为接口故障。`));
    area.append(node('p', '盘中筛选暂停，不将历史行情或资金数据作为当前入选依据。'));
  }
}
async function loadMarketCalendar() {
  try {
    const response = await fetch('./market-calendar.json', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (data.schemaVersion !== 1 || data.timeZone !== 'Asia/Shanghai' || !data.years || !Object.values(data.years).every(y => typeof y.source === 'string' && Array.isArray(y.holidays) && y.holidays.every(h => /^\d{4}-\d{2}-\d{2}$/.test(h.start) && /^\d{4}-\d{2}-\d{2}$/.test(h.end) && h.start <= h.end))) throw new Error();
    marketCalendar = data;
  } catch { marketCalendar = null; }
  renderMarket();
}

function expired(row) {
  const evaluated = Date.parse(row.evaluatedAt);
  const quote = Date.parse(row.quoteAt);
  const age = Date.now() - Math.min(evaluated, quote);
  return !Number.isFinite(age) || age < 0 || age > 180000;
}
function effectiveStatus(row) {
  if (currentMarket().state !== 'open' || !currentMarket().supportedScanTime || expired(row) || row.checks.some(c => c.status === 'unknown')) return 'unknown';
  return row.checks.every(c => c.status === 'pass') ? 'selected' : 'rejected';
}
function render() {
  renderMarket();
  if (!report) return;
  const market = currentMarket();
  const selected = report.stocks.filter(s => effectiveStatus(s) === 'selected').length;
  const unknown = report.stocks.filter(s => effectiveStatus(s) === 'unknown').length;
  summary.replaceChildren(node('h2', market.state === 'closed' ? '休市，等待下一交易日' : report.complete ? '已完成指定范围扫描' : '无法判断：扫描未完成或范围不完整'));
  summary.append(node('p', `范围：${report.scope} · 已处理 ${report.scannedCount} / ${report.universeCount ?? '未知'} 只 · 当前有效入选 ${selected} 只 · 无法判断 ${unknown} 只`));
  summary.append(node('p', `结果生成：${displayTime(report.generatedAt)}；逐股行情时间见下方。`));
  if (!report.complete && market.state !== 'closed') summary.append(node('p', '扫描未完成不能解释为市场上没有符合条件的股票。', 'warning'));
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
    if (expired(stock)) card.append(node('p', market.state === 'closed' ? '休市期间不判断当前是否入选；以下仅为此前逐项记录。' : '行情已过期或缺少行情时间，无法判断当前是否入选。以下为扫描时逐项记录。', 'warning'));
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
  status.textContent = market.state === 'closed' ? '休市，等待下一交易日；盘中筛选暂停。接口诊断与休市状态分别记录。' : matches.length ? `显示 ${matches.length} 条结果；数据缺失或过期均不入选。` :
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
  await loadMarketCalendar();
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
