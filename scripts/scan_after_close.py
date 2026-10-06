"""Free-source, date-locked after-close scan. Never requests intraday data."""
import argparse,json,sys,time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.engine import CHINA,Missing,number
from radar.provider import Eastmoney,DataError,HOSTS
from radar.universe import universe
from radar.scope import restrict,exclusion_reason,SCOPE,POLICY
from radar.after_close import selection_date,session_dates,history_checks,funds_check,result
from scripts.scan_history_market import Reader,atomic,financial_check


def one(record,calendar,target,reader,now):
    if exclusion_reason(record):raise Missing('范围外股票，禁止数据请求')
    checks={};sources=[];errors=[];stage='data_unknown'
    def source(kind,url,status,data_at=None):
        sources.append(dict(kind=kind,name='腾讯配对日线' if kind=='history' else '东方财富全天资金日线',url=url,status=status,dataAt=data_at,fetchedAt=datetime.now(CHINA).isoformat()))
    try:
        short=reader.bars(record['code'],6,'')
        expected=calendar[-4:]
        if not short or short[-1]['date']!=target or [r['date'] for r in short[-4:]]!=expected:
            raise Missing('最近四个日线日期与目标交易日历不一致，不能以旧日线代替')
        amounts=[number(r['volume']) for r in short[-4:]]
        if min(amounts)<=0:raise Missing('最近四日存在停牌或零成交量')
        from decimal import Decimal
        if not all(a<b<=a*Decimal('1.5') for a,b in zip(amounts,amounts[1:])):
            checks['volume']=dict(status='fail',reason='最近三日并非每天均温和放量；已排除，未继续请求其他条件',evidence=dict(dates=expected,volumes=[str(v) for v in amounts]))
            source('history','https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get','available',target)
            row=result(record,target,checks,now,sources,errors);row['stage']='volume_excluded';return row
        raw=reader.bars(record['code'],160,'');qfq=reader.bars(record['code'],160,'qfq')
        checks.update(history_checks(qfq,raw,calendar,target))
        source('history','https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get','available',target)
        stage='history_checked'
    except (DataError,Missing,KeyError,TypeError,ValueError) as error:
        errors.append(dict(kind='history',message=str(error)))
        source('history','https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get','unavailable')
        for key in ('trend','gains','volume'):checks.setdefault(key,dict(status='unknown',reason=str(error),evidence={}))
    if all(checks.get(key,{}).get('status')=='pass' for key in ('trend','gains','volume')):
        stage='complete_chain_attempted'
        earnings=financial_check(Eastmoney(reader.fetch),record['symbol'],now)
        checks['earnings']={k:earnings.get(k,{}) for k in ('status','reason','evidence')}
        sources.extend(dict(s,name='东方财富正式财报/预告') for s in earnings['sources'])
        errors.extend(dict(kind=e['kind'],message=e['reason']) for e in earnings['errors'])
        try:
            data=Eastmoney(reader.fetch).historical_funds(record['symbol'])
            checks['funds']=funds_check(data,target)
            source('funds',HOSTS['funds_history'],'available',data['tradeDate'])
        except (DataError,Missing,KeyError,TypeError,ValueError) as error:
            checks['funds']=dict(status='unknown',reason=str(error),evidence={})
            errors.append(dict(kind='funds',message=str(error)));source('funds',HOSTS['funds_history'],'unavailable')
    row=result(record,target,checks,now,sources,errors);row['stage']=stage;return row


def run(workers=8,output=Path('static/results.json'),requested=None,symbols=None,readiness_attempts=1):
    now=datetime.now(CHINA)
    report=dict(schemaVersion=3,dataMode='real',screeningMode='after_close',scopePolicy=POLICY,scope=SCOPE,
                scanStartedAt=now.isoformat(),generatedAt=now.isoformat(),selectionDate=None,
                complete=False,coverageComplete=False,running=False,dataReady=False,universeCount=None,scannedCount=0,
                stocks=[],errors=[],counts=dict(selected=0,rejected=0,unknown=0),schedule='交易日北京时间20:30触发；等待当日日期数据，不进行盘中扫描')
    try:target=selection_date(now,requested)
    except (Missing,ValueError) as error:
        report.update(state='paused',message=str(error));atomic(output,report);return 0
    report.update(selectionDate=target,state='waiting_data',message='等待目标交易日完整日线及全天资金更新')
    if requested is None and symbols is None and output.exists():
        try:
            previous=json.loads(output.read_text())
            if previous.get('schemaVersion')==3 and previous.get('screeningMode')=='after_close' and previous.get('scopePolicy')==POLICY and previous.get('selectionDate')==target and previous.get('coverageComplete') is True and previous.get('complete') is True and not previous.get('running'):
                print('本交易日完整盘后扫描已执行；不会重复扫描。',flush=True);return 0
        except (OSError,ValueError):pass
    reader=Reader();probes=[]
    try:calendar=session_dates(target)
    except Missing as error:
        report['errors'].append(str(error));atomic(output,report);return 2
    # Readiness checks are NOT full scans. No fallback to a previous date.
    for attempt in range(readiness_attempts):
        errors=[];probes=[]
        try:
            index=reader.bars('sh000001',160,'')
            if not index or index[-1]['date']!=target or [r['date'] for r in index[-120:]]!=calendar:
                raise Missing('上证指数日线尚未更新到目标日或120日历不完整')
            for symbol in ('600519','000001','600036'):
                try:
                    data=Eastmoney(reader.fetch).historical_funds(symbol)
                    funds_check(data,target)
                    probes.append(dict(symbol=symbol,status='available',tradeDate=data['tradeDate'],netInflow=data['netInflow']))
                except (DataError,Missing,ValueError) as error:
                    probes.append(dict(symbol=symbol,status='unknown',reason=str(error)))
            if not any(p['status']=='available' for p in probes):raise Missing('全天主力资金未取得目标日期记录，等待更新；不启动全市场扫描')
            report['dataReady']=True;break
        except (DataError,Missing,ValueError,KeyError,TypeError) as error:errors.append(str(error))
        report.update(errors=errors,readinessProbes=probes,readinessAttempts=attempt+1,generatedAt=datetime.now(CHINA).isoformat())
        atomic(output,report)
        if attempt+1<readiness_attempts:time.sleep(60)
    report.update(readinessProbes=probes,readinessAttempts=attempt+1)
    if not report['dataReady']:
        report.update(errors=errors,generatedAt=datetime.now(CHINA).isoformat());atomic(output,report);return 2
    try:
        listing=universe(reader.fetch);records,stats=restrict(listing['stocks']);report.update(stats)
        if symbols is not None:
            report['excludedRequestedSymbols']=sorted(set(symbols)-{r['symbol'] for r in records})
            records=[r for r in records if r['symbol'] in symbols];report['scope']+='（指定代码验证，非全市场）'
        report.update(universeCount=len(records),universeSource=listing['source'],universeFetchedAt=listing['fetchedAt'],
                      running=True,state='scanning',comparisonDates=calendar[-3:],baselineDate=calendar[-4],historyWindowStart=calendar[0])
        atomic(output,report)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(one,r,calendar,target,reader,now):r for r in records}
            for future in as_completed(futures):
                row=future.result();report['stocks'].append(row)
                report.update(scannedCount=len(report['stocks']),generatedAt=datetime.now(CHINA).isoformat())
                report['counts']={s:sum(r['status']==s for r in report['stocks']) for s in ('selected','rejected','unknown')}
                if report['scannedCount']%100==0:
                    atomic(output,report);print(json.dumps({k:report[k] for k in ('scannedCount','universeCount','counts')},ensure_ascii=False),flush=True)
        report.update(complete=True,coverageComplete=symbols is None and len(report['stocks'])==report['eligibleUniverseCount'],state='completed',message='盘后扫描已完成；必要数据缺失的股票仍无法判断')
    except (DataError,Missing,ValueError,KeyError,TypeError) as error:
        report['errors'].append(str(error));report.update(state='incomplete',message='盘后扫描未完成，不能视为没有符合条件的股票')
    report['stocks'].sort(key=lambda r:r['symbol'])
    report.update(running=False,generatedAt=datetime.now(CHINA).isoformat(),requestsAttempted=reader.requests,
                  preliminaryExcludedCount=sum(r.get('stage')=='volume_excluded' for r in report['stocks']),
                  fullChainAttemptedCount=sum(r.get('stage')=='complete_chain_attempted' for r in report['stocks']))
    atomic(output,report)
    print(json.dumps({k:report[k] for k in ('selectionDate','scannedCount','counts','complete','errors')},ensure_ascii=False),flush=True)
    return 0 if report['complete'] else 2


def main():
    p=argparse.ArgumentParser(description='盘后选股，拒绝旧日期替代；不请求盘中数据')
    p.add_argument('--date',help='明确指定已完成交易日，用于核验；定时任务不得设置此项')
    p.add_argument('--symbols',help='六位代码逗号分隔；仍排除范围外股票')
    p.add_argument('--workers',type=int,choices=range(1,9),default=8)
    p.add_argument('--output',type=Path,default=Path('static/results.json'))
    p.add_argument('--readiness-attempts',type=int,choices=range(1,7),default=1)
    a=p.parse_args();return run(a.workers,a.output,a.date,set(a.symbols.split(',')) if a.symbols else None,a.readiness_attempts)

if __name__=='__main__':raise SystemExit(main())
