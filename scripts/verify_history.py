"""Real few-stock field verification, separate from intraday screening."""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.engine import CHINA
from radar.fallback import HISTORY, market_code, tencent_quote
from radar.provider import Eastmoney, get_json, DataError


def verify(symbol):
    r = {'symbol': symbol, 'checkedAt': datetime.now(CHINA).isoformat(), 'checks': []}
    em = Eastmoney()
    for kind, call in [('eastmoney_history', lambda: em.history(symbol, datetime.now(CHINA))),
                       ('eastmoney_minutes', lambda: em.minutes(symbol)),
                       ('eastmoney_quote_funds', lambda: em.quote(symbol)),
                       ('financial', lambda: em.reports('financial', symbol, datetime.now(CHINA))),
                       ('forecasts', lambda: em.reports('forecasts', symbol, datetime.now(CHINA)))]:
        try:
            value = call()
            if kind == 'financial':
                row = dict(kind=kind, status='received', latestDataAt=value['announcedAt'], period=value['period'])
            elif kind == 'forecasts':
                row = dict(kind=kind, status='received', records=len(value), latestDataAt=max((v['announcedAt'] for v in value), default=None))
            elif kind.endswith('quote_funds'):
                row = dict(kind=kind, status='received', latestDataAt=value[0]['asOf'], fundsFieldPresent=value[1] is not None)
            else:
                row = dict(kind=kind, status='received', records=len(value), latestDataAt=value[-1].get('date',value[-1].get('time')))
            r['checks'].append(row)
        except (DataError, ValueError) as e:
            r['checks'].append(dict(kind=kind,status='unavailable',reason=str(e)))
    for adjustment,key in [('qfq','qfqday'),('','day')]:
        try:
            code=market_code(symbol)
            data=get_json(HISTORY,{'param':f'{code},day,,,160,{adjustment}'})['data'][code]
            rows=data[key]
            if not rows or any(not isinstance(row,list) or len(row)<6 for row in rows):
                raise DataError('日线结构变化')
            r['checks'].append(dict(kind='tencent_'+key,status='received',records=len(rows),latestDataAt=rows[-1][0],
                rowColumnCounts=sorted(set(len(row) for row in rows)),sampleLastRow=rows[-1],
                verifiedHistoricalChangePercent=False,
                reason='已验证日期及OHLC/成交量；无已验证的历史涨幅或除权昨收字段，附加列不猜测映射'))
        except (DataError,KeyError,ValueError,TypeError) as e:
            r['checks'].append(dict(kind='tencent_'+key,status='unavailable',reason=str(e)))
    try:
        q=tencent_quote(symbol)
        r['checks'].append(dict(kind='tencent_quote',status='received',latestDataAt=q['asOf'],
            reason='报价只能对应自身时间戳的交易日，不能补齐前两日历史涨幅'))
    except DataError as e:
        r['checks'].append(dict(kind='tencent_quote',status='unavailable',reason=str(e)))
    return r

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as p: stocks=list(p.map(verify,['600519','000001','300750']))
    report=dict(checkedAt=datetime.now(CHINA).isoformat(),purpose='历史字段及连接诊断，不生成入选结果',stocks=stocks)
    Path('static/history-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
