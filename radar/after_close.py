"""Three completed-session screening, independent of intraday quotes/minutes."""
from decimal import Decimal
from datetime import timedelta, time, date
from .engine import CHINA, Missing, number, earnings
from .historical import verified_change
from .market import calendar_data, trading_day
from .scope import exclusion_reason

RULES = [('trend','120日回撤至少20%，三个完整交易日收盘逐日上升'),
         ('gains','最近三个完整交易日涨幅均在(0%,3%]'),
         ('volume','最近三日全天成交量增幅均在(0%,50%]'),
         ('earnings','最新财报盈利或有效正式预告扭亏'),
         ('funds','第三个交易日全天主力资金净流入大于0')]


def session_dates(target, count=120):
    point=date.fromisoformat(target);result=[];calendar=calendar_data()
    while len(result)<count:
        state=trading_day(point,calendar)
        if state is None:raise Missing('交易所日历未覆盖所需历史日期')
        if state:result.append(point.isoformat())
        point-=timedelta(days=1)
    return list(reversed(result))


def selection_date(now, requested=None):
    now=now.astimezone(CHINA);calendar=calendar_data()
    if requested:
        day=date.fromisoformat(requested)
        if trading_day(day,calendar) is not True:raise Missing('选股日期不是已核实交易日')
        if day>now.date() or (day==now.date() and now.time()<time(18,30)):
            raise Missing('所选交易日尚未进入18:30后的盘后数据核验时段')
        return day.isoformat()
    state=trading_day(now.date(),calendar)
    if state is None:raise Missing('交易所日历未覆盖当前年份')
    if not state:raise Missing('休市，等待下一交易日；不执行盘中或盘后扫描')
    if now.time()<time(18,30):raise Missing('等待北京时间18:30及当日数据更新完整；不执行盘中扫描')
    return now.date().isoformat()


def history_checks(qfq,raw,calendar,target):
    if calendar!=session_dates(target) or len(calendar)!=120:
        raise Missing('指数交易日历与交易所120日历不一致')
    if not qfq or not raw or qfq[-1]['date']!=target or raw[-1]['date']!=target:
        raise Missing('日线最新日期不是选股日；不会改用旧日期')
    q={r['date']:r for r in qfq};u={r['date']:r for r in raw}
    if len(q)!=len(qfq) or len(u)!=len(raw) or any(d not in q or d not in u for d in calendar):
        raise Missing('缺少完整120日同日期复权/原始行情（新股或停牌）')
    rows=[q[d] for d in calendar]
    for row in rows:
        if number(row['volume'])<=0 or number(u[row['date']]['volume'])<=0:
            raise Missing('120日窗口存在停牌或无成交数据')
    changes=[verified_change(q[a],q[b],u[a],u[b]) for a,b in zip(calendar[-4:-1],calendar[-3:])]
    gain_state='unknown' if any(c['status']=='unknown' for c in changes) else 'pass' if all(c['status']=='pass' for c in changes) else 'fail'
    gain=dict(status=gain_state,reason='；'.join(f"{c.get('date',calendar[-3+i])}：{c.get('percent') or '无法判断'}%（{c['reason']}）" for i,c in enumerate(changes)),evidence=dict(days=changes))
    volumes=[]
    for a,b in zip(calendar[-4:-1],calendar[-3:]):
        if any(number(q[d]['volume'])!=number(u[d]['volume']) for d in (a,b)):
            volumes.append(dict(status='unknown',date=b,reason='复权与原始成交量口径不一致'));continue
        old,new=number(u[a]['volume']),number(u[b]['volume'])
        volumes.append(dict(status='pass' if old<new<=old*Decimal('1.5') else 'fail',previousDate=a,date=b,previousVolume=str(old),volume=str(new),percent=str((new/old-1)*100)))
    volume_state='unknown' if any(c['status']=='unknown' for c in volumes) else 'pass' if all(c['status']=='pass' for c in volumes) else 'fail'
    volume=dict(status=volume_state,reason='；'.join(f"{c['date']}：{c.get('percent','无法判断')}%" for c in volumes),evidence=dict(days=volumes,unit='手'))
    # Peak/trough must precede the FIRST of the three completed rising sessions.
    prior=rows[:-3];peak_i=max(range(len(prior)),key=lambda i:number(prior[i]['high']))
    peak=prior[peak_i];later=prior[peak_i+1:]
    trend=dict(status='fail',reason='前期高点之后没有可确认低点',evidence={})
    if later:
        trough=min(later,key=lambda r:number(r['low']));high,low=number(peak['high']),number(trough['low'])
        ascending=number(rows[-3]['close'])<number(rows[-2]['close'])<number(rows[-1]['close'])
        pct=(1-low/high)*100
        trend=dict(status='pass' if low<=high*Decimal('.8') and ascending else 'fail',
                   reason=f"{peak['date']}高点至{trough['date']}低点回撤{pct:.4f}%；最近三个完整收盘逐日上升：{'是' if ascending else '否'}",
                   evidence=dict(peakDate=peak['date'],troughDate=trough['date'],drawdownPercent=str(pct),closingPrices=[str(r['close']) for r in rows[-3:]],dates=calendar[-3:]))
    return dict(trend=trend,gains=gain,volume=volume)


def funds_check(data,target):
    if not isinstance(data,dict) or data.get('tradeDate')!=target:
        raise Missing('全天资金日期不是选股日或数据缺失；不使用旧资金')
    value=number(data.get('netInflow'))
    return dict(status='pass' if value>0 else 'fail',reason=f'{target}全天主力净流入{value:,.2f}元（大单+超大单）',evidence=dict(tradeDate=target,netInflow=str(value),unit='元'))


def result(record,target,checks,now,sources=None,errors=None):
    if exclusion_reason(record):raise Missing('范围外股票不得参与盘后选股')
    complete=[]
    for key,label in RULES:
        c=checks.get(key,dict(status='unknown',reason='必要数据未取得，无法判断',evidence={}))
        complete.append(dict(id=key,label=label,**c))
    state='unknown' if any(c['status']=='unknown' for c in complete) else 'selected' if all(c['status']=='pass' for c in complete) else 'rejected'
    return dict(**record,status=state,checks=complete,selectionDate=target,evaluatedAt=now.isoformat(),
                sources=sources or [],errors=errors or [],screeningMode='after_close')
