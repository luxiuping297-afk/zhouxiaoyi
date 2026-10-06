const search=document.querySelector('#search'),direction=document.querySelector('#direction'),status=document.querySelector('#status'),body=document.querySelector('#stocks'),refresh=document.querySelector('#refresh'),summary=document.querySelector('#summary');
let report=null,marketCalendar=null;
const labels={selected:'入选',rejected:'不满足',unknown:'无法判断',pass:'满足',fail:'不满足'};
function node(tag,text='',className=''){const el=document.createElement(tag);el.textContent=text;el.className=className;return el;}
function displayTime(value){if(typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value))return value;const t=Date.parse(value);return Number.isFinite(t)?new Date(t).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+'（北京时间）':'未提供';}
function link(url,text){try{const u=new URL(url);if(u.protocol!=='https:')return node('span',text);const a=node('a',text);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return node('span',text);}}
function currentMarket(){
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(Date.now()));
 const v=Object.fromEntries(parts.map(p=>[p.type,p.value])),date=`${v.year}-${v.month}-${v.day}`,year=marketCalendar?.years?.[v.year];
 if(!year)return {message:'交易所日历未覆盖当前日期，无法确认交易状态',requiredDate:null};
 function trading(d){const y=marketCalendar.years[d.slice(0,4)];return y&&![0,6].includes(new Date(d+'T00:00:00Z').getUTCDay())&&!y.holidays.some(h=>h.start<=d&&d<=h.end);}
 function nearby(step){const p=new Date(date+'T00:00:00Z');for(let i=0;i<21;i++){p.setUTCDate(p.getUTCDate()+step);const d=p.toISOString().slice(0,10);if(trading(d))return d;}return null;}
 const isDay=trading(date),minute=Number(v.hour)*60+Number(v.minute),requiredDate=isDay&&minute>=900?date:nearby(-1);
 return {requiredDate,source:year.source,nextTradingDate:nearby(1),message:!isDay?'休市，等待下一交易日':minute<900?'盘中不扫描，等待收盘及全天数据更新':'已收盘，等待完整数据；交易日20:30触发盘后选股'};
}
function eligible(row){return /^(600|601|603|605|000|001|002|003)\d{3}$/.test(row.symbol)&&! /^(?:(?:XD|XR|DR))*S?\*?ST/.test(row.name.normalize('NFKC').replace(/\s+/g,'').toUpperCase());}
function effectiveStatus(row){
 if(!report||!currentMarket().requiredDate||report.selectionDate!==currentMarket().requiredDate||row.selectionDate!==report.selectionDate)return 'unknown';
 if(row.checks.some(c=>c.status==='unknown'))return 'unknown';
 const funds=row.checks.find(c=>c.id==='funds');
 if(!funds||funds.evidence?.tradeDate!==report.selectionDate)return 'unknown';
 return row.checks.every(c=>c.status==='pass')?'selected':'rejected';
}
function render(){
 const m=currentMarket(),area=document.querySelector('#market-state');
 if(area){area.replaceChildren(node('h2',m.message));if(m.source)area.append(link(m.source,'交易所官方休市安排'));area.append(node('p',`应核验的最近完整交易日：${m.requiredDate||'无法确认'}；下一交易日：${m.nextTradingDate||'无法确认'}。已停止盘中扫描。`));}
 if(!report)return;
 const counts={selected:0,rejected:0,unknown:0};for(const r of report.stocks)counts[effectiveStatus(r)]++;
 summary.replaceChildren(node('h2',report.state==='waiting_data'?'无法判断：等待选股日数据完整':report.state==='paused'?report.message:`盘后结果 · 选股日期 ${report.selectionDate||'无法确认'}`));
 summary.append(node('p',`选股日期：${report.selectionDate||'尚未扫描'}；最近三日：${(report.comparisonDates||[]).join('、')||'尚未确认'}；前一交易日基准：${report.baselineDate||'尚未确认'}；数据/结果更新时间：${displayTime(report.generatedAt)}。`));
 summary.append(node('p',`范围：${report.scope}；排除前 ${report.beforeExclusionCount??'未知'} 只，排除 ${report.excludedCount??'未知'} 只，保留 ${report.eligibleUniverseCount??'未知'} 只；实际处理 ${report.scannedCount} / ${report.universeCount??'未知'} 只。`));
 summary.append(node('p',`该选股日有效入选 ${counts.selected} 只；不满足 ${counts.rejected} 只；必要链路未全部核验、无法判断 ${counts.unknown} 只。`));
 summary.append(node('p',`前置放量已排除 ${report.preliminaryExcludedCount||0} 只（其余条件未请求，不视为符合）；完整五项链路已尝试 ${report.fullChainAttemptedCount||0} 只。`));
 summary.append(node('p','每天交易日20:30（北京时间）等待当日日线及全天资金更新，随后扫描一次。免费源缺失或日期不一致均无法判断；网页刷新不发起采集。'));
 if(report.selectionDate&&report.selectionDate!==m.requiredDate)summary.append(node('p','这是此前选股日的历史记录，不能作为应核验交易日的结果；不会用旧数据替代。','warning'));
 if(!report.complete)summary.append(node('p','扫描尚未完成或数据未就绪，不能解释为市场上没有符合条件的股票。','warning'));
 for(const e of report.errors)summary.append(node('p',e,'warning'));
 for(const p of report.readinessProbes||[])summary.append(node('p',`全天资金更新核验 ${p.symbol}：${p.status==='available'?p.tradeDate:p.reason}`));
 const q=search.value.trim().toLowerCase();const matches=report.stocks.filter(r=>(r.symbol.includes(q)||r.name.toLowerCase().includes(q))&&(direction.value==='all'||effectiveStatus(r)===direction.value));
 body.replaceChildren();
 for(const r of matches.slice(0,100)){
  const s=effectiveStatus(r),card=node('article','','stock-card');card.append(node('h2',`${r.symbol} ${r.name} · ${labels[s]}`,s));
  card.append(node('p',`选股日 ${r.selectionDate}；核验时间 ${displayTime(r.evaluatedAt)}。`));
  if(r.selectionDate!==m.requiredDate)card.append(node('p','历史记录，无法判断应核验交易日是否入选。','warning'));
  const list=node('ul');for(const c of r.checks)list.append(node('li',`${labels[c.status]} · ${c.label}：${c.reason}`,c.status));card.append(list);
  const detail=node('details');detail.append(node('summary','数据来源、数据日期及更新时间'));
  for(const source of r.sources){const p=node('p',`${source.kind}：${source.status==='available'?'已取得':'无法判断'}；数据日期 ${displayTime(source.dataAt)}；更新时间 ${displayTime(source.fetchedAt)} · `);p.append(link(source.url,source.name));detail.append(p);}
  for(const e of r.errors)detail.append(node('p',`${e.kind}：${e.message}`,'warning'));
  card.append(detail);body.append(card);
 }
 status.textContent=`匹配 ${matches.length} 条，显示前 ${Math.min(matches.length,100)} 条；可输入代码查找。盘后结果按选股日期展示，不使用盘中分钟数据。`;
}
async function load(){
 refresh.disabled=true;status.textContent='正在读取盘后结果…';
 try{
  const response=await fetch('./market-calendar.json',{cache:'no-store'});const d=await response.json();
  if(!response.ok||d.schemaVersion!==1||!d.years)throw new Error();marketCalendar=d;
 }catch{marketCalendar=null;}
 try{
  const response=await fetch('./results.json',{cache:'no-store'});const d=await response.json();
  if(!response.ok||d.schemaVersion!==3||d.screeningMode!=='after_close'||d.scopePolicy!=='sh-sz-mainboard-no-st-v1'||d.dataMode!=='real'||!Array.isArray(d.stocks)||!Array.isArray(d.errors)||!d.stocks.every(r=>typeof r.name==='string'&&typeof r.symbol==='string'&&eligible(r)&&['selected','rejected','unknown'].includes(r.status)&&r.screeningMode==='after_close'&&r.selectionDate===d.selectionDate&&Array.isArray(r.checks)&&r.checks.length===5&&['trend','gains','volume','earnings','funds'].every(id=>r.checks.filter(c=>c.id===id).length===1)&&r.checks.every(c=>['pass','fail','unknown'].includes(c.status))&&Array.isArray(r.sources)&&Array.isArray(r.errors)))throw new Error();
  report=d;render();
 }catch{report=null;body.replaceChildren();summary.replaceChildren(node('h2','无法判断：盘后结果加载失败或仍为旧版盘中格式'));status.textContent='不会使用旧版盘中结果、演示行情或历史候选代替盘后结果。';}
 finally{refresh.disabled=false;}
}
search.addEventListener('input',render);direction.addEventListener('change',render);refresh.addEventListener('click',load);setInterval(render,60000);load();
