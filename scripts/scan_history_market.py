"""Free full-universe historical screening; never creates official selections."""
import argparse,json,sys,time,threading
from pathlib import Path
from datetime import datetime
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.provider import get_json,DataError,Eastmoney
from radar.engine import CHINA,Missing,number,earnings
from radar.fallback import HISTORY,tencent_history
from radar.historical import parse_bars,analyze
from radar.universe import universe
from radar.market import market_status


def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


class Reader:
    def __init__(self):self.requests=0;self.lock=threading.Lock()
    def fetch(self,url,params):
        for attempt in range(2):
            with self.lock:self.requests+=1
            try:return get_json(url,params)
            except DataError as error:
                if attempt or not any(w in str(error) for w in ('HTTP 502','HTTP 503','网络','超时')):raise
                time.sleep(.3)
    def bars(self,code,count,adjustment):
        payload=self.fetch(HISTORY,{'param':f'{code},day,,,{count},{adjustment}'})
        if payload.get('code')!=0:raise DataError('历史行情返回失败代码')
        data=payload.get('data',{}).get(code)
        if not isinstance(data,dict):raise DataError('没有所请求市场证券的历史记录')
        quotes=data.get('qt')
        identity=quotes.get(code) if isinstance(quotes,dict) else None
        if not isinstance(identity,list) or len(identity)<3 or identity[2]!=code[2:]:
            raise DataError('历史行情缺少可核验的证券身份')
        key='qfqday' if adjustment else 'day'
        if key not in data:raise DataError('缺少明确的前复权/不复权字段，不能互相替代')
        return parse_bars(data[key])


def volume_prefilter(rows,calendar):
    last=[r for r in rows if r['date']<=calendar[-1]][-3:]
    if [r['date'] for r in last]!=calendar[-3:]:raise Missing('缺少前两个交易日及比较基准，停牌或日期不完整')
    volumes=[number(r['volume']) for r in last]
    if min(volumes)<=0:raise Missing('比较日成交量为零或停牌')
    from decimal import Decimal
    passed=all(old<new<=old*Decimal('1.5') for old,new in zip(volumes,volumes[1:]))
    return passed,[dict(previousDate=a['date'],date=b['date'],percent=str((number(b['volume'])/number(a['volume'])-1)*100)) for a,b in zip(last,last[1:])]


def financial_check(provider,symbol,now):
    bundle={};errors=[];sources=[]
    for kind in ('financial','forecasts'):
        try:
            bundle[kind]=provider.reports(kind,symbol,now)
            sources.append(dict(kind=kind,status='available',url='https://datacenter-web.eastmoney.com/api/data/v1/get',fetchedAt=datetime.now(CHINA).isoformat()))
            # Profitable latest official report satisfies the OR; no forecast required.
            if kind=='financial':
                try:
                    passed,reason,evidence=earnings(bundle,now)
                    if passed:return dict(status='pass',reason=reason,evidence=evidence,sources=sources,errors=errors)
                except Missing:pass
        except (DataError,ValueError,KeyError,TypeError) as e:
            errors.append(dict(kind=kind,reason=str(e)));sources.append(dict(kind=kind,status='unavailable',url='https://datacenter-web.eastmoney.com/api/data/v1/get',fetchedAt=datetime.now(CHINA).isoformat()))
    try:
        passed,reason,evidence=earnings(bundle,now)
        return dict(status='pass' if passed else 'fail',reason=reason,evidence=evidence,sources=sources,errors=errors)
    except (Missing,KeyError,TypeError) as e:return dict(status='unknown',reason=str(e),sources=sources,errors=errors)


def screen(record,calendar,reader):
    base={**record,'formalSelection':False,'historyAsOf':None,'expectedHistoryDate':calendar[-1]}
    try:
        short=reader.bars(record['code'],4,'')
        base['sourceMostRecentDate']=short[-1]['date'] if short else None
        passed,volumes=volume_prefilter(short,calendar)
        base['historyAsOf']=calendar[-1]
        if not passed:return dict(**base,state='volume_rejected',dailyVolumes=volumes,otherConditions='未继续请求；已不满足必要的连续温和放量条件')
        raw=reader.bars(record['code'],160,'');qfq=reader.bars(record['code'],160,'qfq')
        row=analyze(record['symbol'],qfq,raw,calendar)
        components=[c['status'] for c in row['gains']+row['dailyVolumes']]+[row['drawdown']['status']]
        row.update(name=record['name'],code=record['code'],exchange=record['exchange'],source=HISTORY,fetchedAt=datetime.now(CHINA).isoformat())
        if 'unknown' in components:
            reasons=[c.get('reason','必要字段无法判断') for c in row['gains']+row['dailyVolumes']+[row['drawdown']] if c['status']=='unknown']
            return dict(**row,state='history_unknown',failureReason='；'.join(dict.fromkeys(reasons)))
        if not all(s=='pass' for s in components):return dict(**row,state='history_rejected')
        # Day-three turnaround is still unknown. Recent completed closes can be
        # shown separately, never substituted for current intraday reversal.
        return dict(**row,state='technical_candidate')
    except (DataError,Missing,ValueError,KeyError,TypeError) as e:
        return dict(**base,state='data_failed',failureReason=str(e))


def run(workers=8,output=Path('static/historical-market.json'),symbols=None):
    now=datetime.now(CHINA);reader=Reader();started=now.isoformat()
    rows=[]
    audit_path=output.with_name('historical-market-audit.json')
    report=dict(schemaVersion=1,dataMode='real',historicalOnly=True,formalSelection=False,
        startedAt=started,generatedAt=started,scope='沪深京全A股历史筛选',running=True,coverageComplete=False,
        universeCount=None,scannedCount=0,failureCount=0,candidateCount=0,technicalCandidateCount=0,
        historicalCandidates=[],technicalCandidates=[],failures=[],errors=[],marketStatus=market_status(now))
    atomic(output,report)
    atomic(audit_path,dict(generatedAt=started,dataMode='real',historicalOnly=True,formalSelection=False,stocks=[]))
    try:
        listing=universe(reader.fetch)
        atomic('/tmp/radar-market-universe.json',listing)
        records=listing['stocks'];calendar=[r['date'] for r in tencent_history('000001',now,index=True,fetch=reader.fetch)][-120:]
        if len(calendar)!=120:raise DataError('指数日历不足120交易日')
        report.update(universeCount=len(records),universeSource=listing['source'],universeFetchedAt=listing['fetchedAt'],exchangeUniverseCounts=listing['exchangeCounts'],
            historyAsOf=calendar[-1],comparisonDates=calendar[-3:],historyWindowStart=calendar[0])
        if symbols is not None:
            records=[r for r in records if r['symbol'] in symbols];report['scope']='少量真实股票全链路预检（不是全市场扫描）'
        rows=[];counts=Counter();exchange_attempts=Counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures={pool.submit(screen,r,calendar,reader):r for r in records}
            for future in as_completed(futures):
                row=future.result();rows.append(row);counts[row['state']]+=1;exchange_attempts[row['exchange']]+=1
                if row['state']=='technical_candidate':
                    row['earnings']=financial_check(Eastmoney(reader.fetch),row['symbol'],now)
                    report['technicalCandidates'].append(row)
                    if row['earnings']['status']=='pass':report['historicalCandidates'].append(row)
                failure=row.get('failureReason') or (row.get('earnings',{}).get('reason') if row.get('earnings',{}).get('status')=='unknown' else None)
                if failure:report['failures'].append(dict(symbol=row['symbol'],name=row['name'],exchange=row['exchange'],reason=failure,state=row['state']))
                report.update(scannedCount=len(rows),failureCount=len(report['failures']),candidateCount=len(report['historicalCandidates']),technicalCandidateCount=len(report['technicalCandidates']),
                    stageCounts=dict(counts),fullHistoryAnalyzedCount=counts['history_unknown']+counts['history_rejected']+counts['technical_candidate'],financialCheckedCount=len(report['technicalCandidates']),exchangeScannedCounts=dict(exchange_attempts),requestsAttempted=reader.requests,generatedAt=datetime.now(CHINA).isoformat())
                if len(rows)%100==0:
                    atomic(audit_path,dict(generatedAt=report['generatedAt'],dataMode='real',historicalOnly=True,formalSelection=False,stocks=rows))
                    atomic(output,report);print(json.dumps({k:report[k] for k in ('scannedCount','universeCount','candidateCount','failureCount','stageCounts')},ensure_ascii=False),flush=True)
        report.update(running=False,coverageComplete=symbols is None and len(rows)==listing['reportedTotal'],generatedAt=datetime.now(CHINA).isoformat(),
            financialCounts={s:sum(r['earnings']['status']==s for r in report['technicalCandidates']) for s in ('pass','fail','unknown')})
    except (DataError,Missing,KeyError,TypeError,ValueError) as e:
        report.update(running=False);report['errors'].append(str(e))
    atomic(audit_path,dict(generatedAt=report['generatedAt'],dataMode='real',historicalOnly=True,formalSelection=False,stocks=rows))
    atomic(output,report)
    print(json.dumps({k:report.get(k) for k in ('coverageComplete','scannedCount','universeCount','candidateCount','technicalCandidateCount','failureCount','stageCounts','errors')},ensure_ascii=False),flush=True)
    return 0 if report['coverageComplete'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=8,choices=range(1,9));p.add_argument('--symbols');p.add_argument('--output',type=Path,default=Path('static/historical-market.json'))
    args=p.parse_args();raise SystemExit(run(args.workers,args.output,set(args.symbols.split(',')) if args.symbols else None))
