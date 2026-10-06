"""Fetch three real paired histories; publish separate, never formal selections."""
import sys,json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.engine import CHINA, Missing
from radar.provider import DataError,get_json
from radar.fallback import HISTORY,market_code,tencent_history
from radar.historical import analyze,parse_bars
from radar.market import market_status
from radar.universe import universe
from radar.scope import restrict, exclusion_reason, POLICY, SCOPE

def one(record, calendar):
    symbol=record['symbol']
    try:
        if exclusion_reason(record):raise Missing('不在沪深主板非ST范围内，未采集')
        code=market_code(symbol);pairs={}
        for adj,key in [('qfq','qfqday'),('','day')]:
            data=get_json(HISTORY,{'param':f'{code},day,,,160,{adj}'})['data'][code]
            pairs[key]=parse_bars(data[key])
        row=analyze(symbol,pairs['qfqday'],pairs['day'],calendar)
        row.update(name=record['name'],exchange=record['exchange'],source=HISTORY,fetchedAt=datetime.now(CHINA).isoformat())
        return row
    except (DataError,Missing,KeyError,TypeError,ValueError) as e:
        return dict(symbol=symbol,status='unknown',formalSelection=False,error=str(e))
def main():
    now=datetime.now(CHINA)
    errors=[]
    try:
        eligible,_=restrict(universe()['stocks'])
        identities={r['symbol']:r for r in eligible}
        samples=[identities[s] for s in ('600519','000001','600036') if s in identities]
        calendar=[p['date'] for p in tencent_history('000001',now,index=True)][-120:]
        with ThreadPoolExecutor(max_workers=3) as pool:
            stocks=list(pool.map(lambda record:one(record,calendar),samples))
    except (DataError, Missing, KeyError, TypeError, ValueError) as error:
        stocks=[];errors.append('证券身份或交易日历无法核验：'+str(error))
    report=dict(schemaVersion=1,dataMode='real',historicalOnly=True,formalSelection=False,
        generatedAt=datetime.now(CHINA).isoformat(),marketStatus=market_status(now),scopePolicy=POLICY,scope=SCOPE,errors=errors,
        referenceNextTradingDate=market_status(now)['nextTradingDate'],stocks=stocks)
    output=Path('static/historical-analysis.json')
    temporary=output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(output)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 2 if errors or len(stocks)!=3 or any('error' in row for row in stocks) else 0

if __name__=='__main__':
    raise SystemExit(main())
