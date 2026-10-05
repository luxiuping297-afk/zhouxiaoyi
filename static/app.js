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
  summary.append(node('p', `盘中正式筛选范围：${report.scope} · 已处理 ${report.scannedCount} / ${report.universeCount ?? '未知'} 只 · 当前有效入选 ${selected} 只 · 无法判断 ${unknown} 只`));
  summary.append(node('p', '上述数量仅指盘中正式筛选；沪深京历史扫描数量及历史候选见下方独立区域。'));
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
function percentage(value) {
  const number = Number(value);
  return value != null && Number.isFinite(number) ? number.toFixed(4) + '%' : '无法判断';
}
async function loadHistoricalAnalysis() {
  const area = document.querySelector('#historical-checks');
  if (!area) return;
  try {
    const response = await fetch('./historical-analysis.json', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (data.schemaVersion !== 1 || data.dataMode !== 'real' || data.historicalOnly !== true || data.formalSelection !== false || !Array.isArray(data.stocks) || !data.stocks.every(s => s.formalSelection === false && s.status === 'unknown')) throw new Error();
    area.replaceChildren(node('h2', '历史核验（不属于正式入选）'));
    area.append(node('p', `核验：${displayTime(data.generatedAt)}；以下只检查已完成交易日，不补造第三天盘中数据。`));
    for (const row of data.stocks) {
      const card = node('article', '', 'stock-card');
      card.append(node('h3', `${row.symbol} · 完整筛选：无法判断`));
      if (row.error) { card.append(node('p', row.error, 'warning')); area.append(card); continue; }
      if (!Array.isArray(row.gains) || !Array.isArray(row.dailyVolumes) || !row.drawdown) throw new Error();
      card.append(node('p', `历史截至 ${row.historyAsOf}；120交易日窗口 ${row.windowStart} 至 ${row.historyAsOf}。`));
      const list = node('ul', '');
      for (const gain of row.gains) list.append(node('li', `${gain.date || ''} 涨幅：${percentage(gain.percent)} · ${labels[gain.status]}；${gain.reason}；区间 ${percentage(gain.lowerPercent)} ～ ${percentage(gain.upperPercent)}`, gain.status));
      for (const volume of row.dailyVolumes) list.append(node('li', `${volume.date} 日成交量较 ${volume.previousDate || '前一日'}：${percentage(volume.percent)} · ${labels[volume.status]}${volume.reason ? '；' + volume.reason : ''}`, volume.status));
      const drawdown = row.drawdown;
      list.append(node('li', `120日历史回撤：${percentage(drawdown.percent)} · ${labels[drawdown.status]}（仅回撤子条件）；高点 ${drawdown.peakDate || '无法判断'} → 后续低点 ${drawdown.troughDate || '无法判断'}`, drawdown.status));
      list.append(node('li', `最近三个已完成交易日收盘持续向上：${drawdown.historicalTurnUp ? '成立' : '未成立或无法判断'}；今日止跌转向仍无法判断。`));
      list.append(node('li', '第三天涨幅、盘中同刻成交量、主力资金：无法判断。不得作为正式入选。', 'unknown'));
      card.append(list);
      card.append(link(row.source, '腾讯历史日线来源'));
      area.append(card);
    }
  } catch { area.replaceChildren(node('h2', '历史核验记录不可用'), node('p', '无法判断；不会补入演示或推测结果。')); }
}
function historicalCandidateValid(row, includeEarnings) {
  return row && row.formalSelection === false && row.status === 'unknown' && Array.isArray(row.gains) && row.gains.length === 2 && row.gains.every(c => c.status === 'pass') && Array.isArray(row.dailyVolumes) && row.dailyVolumes.length === 2 && row.dailyVolumes.every(c => c.status === 'pass') && row.drawdown?.status === 'pass' && (!includeEarnings || row.earnings?.status === 'pass');
}
function marketCandidateCard(row, qualified) {
  const card = node('article', '', 'stock-card');
  card.append(node('h3', `${row.symbol} ${row.name}（${row.exchange}） · ${qualified ? '历史候选' : '仅技术历史条件通过'} · 非正式入选`));
  card.append(node('p', `行情日期：${row.historyAsOf}；数据采集：${displayTime(row.fetchedAt)}。`));
  card.append(node('p', `前两日涨幅：${row.gains.map(c => c.date + ' ' + percentage(c.percent)).join(' / ')}；日成交量增幅：${row.dailyVolumes.map(c => percentage(c.percent)).join(' / ')}；120日回撤 ${percentage(row.drawdown.percent)}。`));
  card.append(node('p', `盈利/正式扭亏：${labels[row.earnings.status]} · ${row.earnings.reason}`, row.earnings.status));
  const evidence = row.earnings.evidence;
  if (evidence?.report) card.append(node('p', `财报报告期 ${evidence.report.period}；公告日期 ${evidence.report.announcedAt}。`));
  if (evidence?.forecast) card.append(node('p', `正式预告报告期 ${evidence.forecast.period}；公告日期 ${evidence.forecast.announcedAt}。`));
  card.append(node('p', '今日转向、第三天涨幅、盘中同刻成交量、主力资金：无法判断。不会列为正式入选。', 'unknown'));
  card.append(link(row.source, '历史行情来源'));
  for (const source of row.earnings.sources || []) {
    card.append(node('span', ' · '), link(source.url, source.kind === 'financial' ? '正式财报来源' : '正式预告来源'));
  }
  return card;
}
async function loadHistoricalMarket() {
  const area = document.querySelector('#historical-market');
  if (!area) return;
  try {
    const response = await fetch('./historical-market.json', {cache: 'no-store'});
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (data.schemaVersion !== 1 || data.dataMode !== 'real' || data.historicalOnly !== true || data.formalSelection !== false || !Array.isArray(data.historicalCandidates) || !Array.isArray(data.technicalCandidates) || !data.historicalCandidates.every(s => historicalCandidateValid(s, true)) || !data.technicalCandidates.every(s => historicalCandidateValid(s, false)) || data.candidateCount !== data.historicalCandidates.length) throw new Error();
    area.replaceChildren(node('h2', data.running ? '全市场历史扫描进行中' : data.coverageComplete ? '沪深京历史扫描已完成（非正式入选）' : '历史扫描覆盖不完整'));
    area.append(node('p', `范围：${data.scope}；实际已尝试 ${data.scannedCount} / ${data.universeCount ?? '未知'} 只；历史候选（技术+盈利/扭亏已核验）${data.candidateCount} 只；技术历史条件通过 ${data.technicalCandidateCount} 只；失败或无法判断 ${data.failureCount} 只。`));
    area.append(node('p', `行情截至：${data.historyAsOf || '无法确认'}；比较交易日：${(data.comparisonDates || []).join('、')}；120日窗口从 ${data.historyWindowStart || '无法确认'} 开始；报告更新：${displayTime(data.generatedAt)}。`));
    const exchangeUniverse = data.exchangeUniverseCounts || {};
    const exchangeScanned = data.exchangeScannedCounts || {};
    area.append(node('p', ['沪', '深', '京'].map(x => `${x}市实际尝试 ${exchangeScanned[x] || 0} / ${exchangeUniverse[x] ?? '未知'} 只`).join('；')));
    const stages = data.stageCounts || {};
    const analyzed = (stages.history_unknown || 0) + (stages.history_rejected || 0) + (stages.technical_candidate || 0);
    area.append(node('p', `分阶段核验：${stages.volume_rejected || 0} 只已不满足连续温和放量，未继续请求120日日线；${analyzed} 只完成120日历史分析；${data.technicalCandidates.length} 只核验财报/正式预告。失败数量包含采集失败、数据不完整、涨幅精度或财务无法判断，不包含明确不满足筛选条件。`));
    area.append(node('p', '历史候选只确认截至上述日期的历史条件；全部盘中条件仍需验证。正式入选在下方独立展示，历史候选不会加入正式结果。', 'warning'));
    if (data.universeSource) area.append(link(data.universeSource, '全市场证券列表来源'));
    for (const error of data.errors || []) area.append(node('p', error, 'warning'));
    const candidates = node('details', '');
    candidates.open = true;
    candidates.append(node('summary', `历史候选：${data.historicalCandidates.length} 只（财务已核验，非正式入选）`));
    for (const row of data.historicalCandidates) candidates.append(marketCandidateCard(row, true));
    if (!data.historicalCandidates.length) candidates.append(node('p', data.running || !data.coverageComplete ? '扫描尚未完成，不能解释为全市场没有历史候选。' : '本次已获取的数据中没有确认通过全部历史和财务条件的股票；失败记录仍不能排除。'));
    area.append(candidates);
    const pending = data.technicalCandidates.filter(row => row.earnings.status !== 'pass');
    const financial = node('details', '');
    financial.append(node('summary', `技术条件通过，但财务不满足或无法判断：${pending.length} 只`));
    for (const row of pending) financial.append(marketCandidateCard(row, false));
    area.append(financial);
    const failures = node('details', '');
    failures.append(node('summary', `失败/无法判断记录：${data.failureCount} 只`));
    for (const failure of (data.failures || []).slice(0, 20)) failures.append(node('p', `${failure.symbol} ${failure.name}（${failure.exchange}）：${failure.reason}`));
    const reportLink = node('a', '查看全部统计和失败记录'); reportLink.href = './historical-market.json'; failures.append(reportLink);
    // The relative JSON links remain within the published static directory.
    const audit = node('a', '查看逐股扫描审计记录'); audit.href = './historical-market-audit.json'; failures.append(node('span', ' · '), audit);
    area.append(failures);
  } catch { area.replaceChildren(node('h2', '全市场历史扫描报告不可用'), node('p', '无法确认扫描覆盖或候选条件；不会以样本或演示结果替代。')); }
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
  await loadHistoricalAnalysis();
  await loadHistoricalMarket();
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
