// Synthetic fixtures stay in memory and are never published as market results.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const now=Date.parse('2026-10-06T20:30:00+08:00');
class Clock extends Date{static now(){return now;}}
function el(tag=''){return {tag,value:'',textContent:'',children:[],className:'',disabled:false,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},addEventListener(){}};}
function text(x){return x.textContent+' '+x.children.map(text).join(' ');}
function stock(overrides={}){return {symbol:'600000',name:'<script>测试输入</script>',status:'selected',selectionDate:'2026-09-30',screeningMode:'after_close',evaluatedAt:'2026-09-30T20:30:00+08:00',checks:['trend','gains','volume','earnings','funds'].map(id=>({id,label:id,status:'pass',reason:'test-only',evidence:id==='funds'?{tradeDate:'2026-09-30'}:{}})),sources:[{kind:'funds',status:'available',name:'test',url:'javascript:alert(1)'}],errors:[],...overrides};}
async function run(rows,options={}){
 const nodes={};for(const id of ['search','direction','status','stocks','refresh','summary','market-state'])nodes['#'+id]=el();nodes['#direction'].value='all';const calls=[];
 const report={schemaVersion:3,screeningMode:'after_close',scopePolicy:'sh-sz-mainboard-no-st-v1',dataMode:'real',selectionDate:'2026-09-30',comparisonDates:['2026-09-28','2026-09-29','2026-09-30'],complete:true,state:'completed',scope:'test-only',scannedCount:rows.length,universeCount:rows.length,generatedAt:'2026-09-30T20:30:00+08:00',stocks:rows,errors:[],...options.report};
 const context=vm.createContext({Date:options.clock||Clock,URL,setInterval(){},document:{querySelector:id=>nodes[id],createElement:el},fetch:async url=>{calls.push(url);if(options.fail&&url.endsWith('results.json'))throw new Error();return {ok:true,json:async()=>url.endsWith('results.json')?report:options.badCalendar?{}:JSON.parse(fs.readFileSync('static/market-calendar.json','utf8'))}}});
 vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);await new Promise(r=>setImmediate(r));return {nodes,context,calls};
}
(async()=>{
 let r=await run([stock()]);assert.match(text(r.nodes['#summary']),/有效入选 1 只/);assert.equal(r.nodes['#stocks'].children.length,1);assert.match(text(r.nodes['#stocks']),/<script>测试输入<\/script>/);assert.match(text(r.nodes['#market-state']),/休市，等待下一交易日/);assert.deepEqual(r.calls,['./market-calendar.json','./results.json']);assert.equal(r.nodes['#stocks'].children[0].children.at(-1).children[1].children[0].tag,'span');
 r.nodes['#search'].value='不存在';vm.runInContext('render()',r.context);assert.equal(r.nodes['#stocks'].children.length,0);
 const missing=stock();missing.checks[4].status='unknown';r=await run([missing]);assert.match(text(r.nodes['#summary']),/无法判断 1 只/);
 const fail=stock();fail.checks[2].status='fail';r=await run([fail]);assert.match(text(r.nodes['#summary']),/不满足 1 只/);
 const stale=stock();stale.checks[4].evidence.tradeDate='2026-09-29';r=await run([stale]);assert.match(text(r.nodes['#summary']),/有效入选 0 只/);
 class NextDay extends Date{static now(){return Date.parse('2026-10-08T20:30:00+08:00')}}r=await run([stock()],{clock:NextDay});assert.match(text(r.nodes['#summary']),/不会用旧数据替代/);assert.match(text(r.nodes['#summary']),/有效入选 0 只/);
 r=await run([stock()],{report:{schemaVersion:2,screeningMode:'intraday'}});assert.equal(r.nodes['#stocks'].children.length,0);assert.match(text(r.nodes['#summary']),/旧版盘中/);
 r=await run([stock({symbol:'300750'})]);assert.equal(r.nodes['#stocks'].children.length,0);
 r=await run([stock({name:'XD*ST测试'})]);assert.equal(r.nodes['#stocks'].children.length,0);
 r=await run([stock()],{badCalendar:true});assert.match(text(r.nodes['#summary']),/有效入选 0 只/);
 r=await run([],{fail:true});assert.match(text(r.nodes['#summary']),/加载失败/);
 console.log('PASS: 盘后日期、三日结果、缺失资金、旧数据拒绝、范围排除、安全文本、搜索与休市展示');
})().catch(e=>{console.error(e);process.exitCode=1});
