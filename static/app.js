const search = document.querySelector('#search');
const direction = document.querySelector('#direction');
const status = document.querySelector('#status');
const body = document.querySelector('#stocks');
const refresh = document.querySelector('#refresh');
let stocks = [];
function render() {
  const query = search.value.trim().toLowerCase();
  const matches = stocks.filter(s =>
    (s.symbol.includes(query) || s.name.toLowerCase().includes(query)) &&
    (direction.value === 'all' || (direction.value === 'up' && s.changePercent > 0) || (direction.value === 'down' && s.changePercent < 0))
  ).sort((a, b) => b.changePercent - a.changePercent);
  body.replaceChildren();
  for (const s of matches) {
    const row = document.createElement('tr');
    [s.symbol, s.name, s.price.toFixed(2), `${s.changePercent > 0 ? '+' : ''}${s.changePercent.toFixed(2)}%`].forEach((value, i) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      if (i === 3) cell.className = s.changePercent > 0 ? 'up' : s.changePercent < 0 ? 'down' : '';
      row.append(cell);
    });
    body.append(row);
  }
  status.textContent = matches.length ? `显示 ${matches.length} / ${stocks.length} 只股票 · 演示行情` : '没有符合条件的股票';
}
async function load() {
  refresh.disabled = true;
  status.textContent = '正在加载…';
  try {
    const response = await fetch('./stocks.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('请求失败');
    const data = await response.json();
    if (!Array.isArray(data.stocks) || !data.stocks.every(s => typeof s.symbol === 'string' && typeof s.name === 'string' && Number.isFinite(s.price) && Number.isFinite(s.changePercent))) throw new Error('数据格式错误');
    stocks = data.stocks;
    render();
  } catch (error) {
    stocks = [];
    body.replaceChildren();
    status.textContent = '行情加载失败，请点击刷新重试。';
  } finally { refresh.disabled = false; }
}
search.addEventListener('input', render);
direction.addEventListener('change', render);
refresh.addEventListener('click', load);
load();
