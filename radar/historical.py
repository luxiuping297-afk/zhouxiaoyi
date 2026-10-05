"""Historical checks only; paired raw/qfq bars cannot certify live screening."""
from decimal import Decimal
from .engine import number, Missing


def verified_change(previous, current, raw_previous, raw_current):
    # Older qfq bars can subtract future cash dividends. Their close ratio is not
    # generally the exchange daily return. Never infer an ex-rights reference.
    for adjusted, raw in ((previous, raw_previous), (current, raw_current)):
        for key in ('open', 'close', 'high', 'low'):
            if number(adjusted[key]) != number(raw[key]):
                return dict(status='unknown', percent=None, reason='复权价与原价不同，缺少当日除权昨收/复权因子，不能可靠计算市场涨幅')
        if adjusted.get('corporateAction') or raw.get('corporateAction'):
            return dict(status='unknown', percent=None, reason='存在未解释的公司行动元数据，不能推定无除权除息')
    a,b = number(raw_previous['close']),number(raw_current['close'])
    if min(a,b)<=0:
        raise Missing('原始收盘价无效')
    # Same-source qfq prices are rounded: bound both operands using a full displayed
    # decimal quantum (rounding/truncation are not publicly specified). Require the WHOLE interval on one side.
    def quantum(value):
        return Decimal(1).scaleb(Decimal(str(value)).as_tuple().exponent)
    ea, eb = quantum(previous['close']), quantum(current['close'])
    if a<=ea:
        raise Missing('价格精度不足')
    low=((b-eb)/(a+ea)-1)*100
    high=((b+eb)/(a-ea)-1)*100
    nominal=(b/a-1)*100
    state='pass' if low>0 and high<=3 else 'fail' if high<=0 or low>3 else 'unknown'
    return dict(status=state,percent=str(nominal),lowerPercent=str(low),upperPercent=str(high),
        previousDate=raw_previous['date'],date=raw_current['date'],
        reason='复权/原价一致；同源相邻收盘价计算，并检查舍入区间' if state!='unknown' else '舍入区间跨越0%或3%边界，缺少更精确除权昨收，无法判断')


def parse_bars(rows):
    result=[]
    for row in rows:
        if not isinstance(row,list) or len(row)<6:
            raise Missing('日线字段缺失')
        point=dict(zip(('date','open','close','high','low','volume'),row[:6]))
        point['corporateAction']=row[6] if len(row)>6 else None
        for key in ('open','close','high','low','volume'):number(point[key])
        if not number(point['low'])<=number(point['close'])<=number(point['high']) or number(point['low'])<=0:
            raise Missing('日线OHLC无效')
        result.append(point)
    dates=[p['date'] for p in result]
    if dates!=sorted(set(dates)):
        raise Missing('日线日期重复或乱序')
    return result


def analyze(symbol, qfq, raw, calendar):
    q={p['date']:p for p in qfq};r={p['date']:p for p in raw}
    dates=calendar[-120:]
    if len(dates)!=120 or any(d not in q or d not in r for d in dates):
        raise Missing('缺少完整120交易日的同日期日线或指数交易日历')
    rows=[q[d] for d in dates]
    if any(number(p['volume'])<=0 for p in rows):
        raise Missing('包含停牌/零成交交易日，不能判断连续条件')
    gains=[verified_change(q[a],q[b],r[a],r[b]) for a,b in zip(dates[-3:-1],dates[-2:])]
    volumes=[]
    for a,b in zip(dates[-3:-1],dates[-2:]):
        if any(number(q[d]['volume'])!=number(r[d]['volume']) for d in (a,b)):
            volumes.append(dict(status='unknown',date=b,reason='复权与原价成交量口径不一致'));continue
        old,new=number(r[a]['volume']),number(r[b]['volume'])
        volumes.append(dict(status='pass' if old<new<=old*Decimal('1.5') else 'fail',
            previousDate=a,date=b,previousVolume=str(old),volume=str(new),
            percent=str((new/old-1)*100)))
    prior=rows[:-2]
    peak_index=max(range(len(prior)),key=lambda i:number(prior[i]['high']))
    peak=prior[peak_index];later=prior[peak_index+1:]
    drawdown=dict(status='fail',reason='前期高点之后没有可确认低点')
    if later:
        trough=min(later,key=lambda p:number(p['low']));peak_price=number(peak['high']);low=number(trough['low'])
        drawdown=dict(status='pass' if low<peak_price*Decimal('.8') else 'fail',
            peakDate=peak['date'],peakHigh=str(peak_price),troughDate=trough['date'],troughLow=str(low),
            percent=str((1-low/peak_price)*100),
            historicalTurnUp=number(rows[-3]['close'])<number(rows[-2]['close'])<number(rows[-1]['close']),
            reason='只确认历史回撤和收盘走势；今日止跌转向仍需有效盘中报价')
    differences=[d for d in dates if number(q[d]['close'])!=number(r[d]['close'])]
    return dict(symbol=symbol,status='unknown',formalSelection=False,historyAsOf=dates[-1],windowStart=dates[0],
        completedSessions=120,adjustment='腾讯同次核验前复权日线；每日涨幅仅在相邻复权/原始OHLC一致且误差区间不跨阈值时计算',
        differingAdjustedDates=len(differences),firstAdjustedDifference=differences[0] if differences else None,
        gains=gains,dailyVolumes=volumes,drawdown=drawdown,
        intradayVolume=dict(status='unknown',reason='休市期间不能验证当日与前日同一分钟累计量'),
        mainFunds=dict(status='unknown',reason='未验证扫描时主力资金数据及时间戳'),
        thirdDayGain=dict(status='unknown',reason='没有当前交易时段的有效报价'),
        completeTrend=dict(status='unknown',reason='120日历史回撤不等于今日止跌转向成立'))
