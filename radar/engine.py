"""Pure screening rules. Synthetic inputs belong only in tests, never the website."""
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from .market import market_status

CHINA = ZoneInfo('Asia/Shanghai')
RULES = [
    ('trend', '120交易日高点后跌幅超过20%并转头向上'),
    ('gains', '连续三天涨幅均在(0%, 3%]'),
    ('volume', '连续放量且增幅均在(0%, 50%]，今日比较昨日同分钟'),
    ('earnings', '最新财报盈利或有效正式预告扭亏为盈'),
    ('funds', '扫描时当日主力净流入大于0'),
]


class Missing(ValueError):
    pass


def number(value):
    try:
        if isinstance(value, bool) or value is None:
            raise InvalidOperation
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError):
        raise Missing('必要数值缺失或无效') from None


def timestamp(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(CHINA)
    except (ValueError, TypeError):
        raise Missing('必要时间戳缺失或未注明时区') from None


def fresh(value, now):
    market = market_status(now)
    if market['state'] != 'open':
        raise Missing(market['message'])
    if now.weekday() >= 5 or not (time(9, 31) <= now.time() <= time(11, 30) or time(13, 1) <= now.time() <= time(14, 57)):
        raise Missing('扫描时刻不在支持的连续竞价时段，不能判断盘中条件')
    point = timestamp(value)
    if not 0 <= (now - point).total_seconds() <= 180:
        raise Missing('行情非扫描时刻数据（允许延迟最多180秒）')
    if point.date() != now.date():
        raise Missing('行情不是今日数据')
    return point


def daily_window(bundle, now):
    dates = bundle.get('calendar') or []
    history = bundle.get('history') or []
    if len(dates) < 120:
        raise Missing('缺少120个已完成交易日的交易日历')
    dates = dates[-120:]
    if dates != sorted(set(dates)) or any(d >= now.date().isoformat() for d in dates):
        raise Missing('交易日历重复、乱序或包含未完成交易日')
    indexed = {row['date']: row for row in history}
    if len(indexed) != len(history):
        raise Missing('日线日期重复')
    if any(d not in indexed for d in dates):
        raise Missing('120个交易日日线不完整（新股、停牌或接口缺失）')
    rows = [indexed[d] for d in dates]
    for row in rows:
        close, high, low = (number(row.get(k)) for k in ('close', 'high', 'low'))
        if low <= 0 or not low <= close <= high:
            raise Missing('复权日线价格无效')
        if number(row.get('volume')) <= 0:
            raise Missing('存在无成交交易日，不能按连续交易日判断')
    return rows


def trend(bundle, now):
    rows = daily_window(bundle, now)
    # Prior peak and subsequent trough must precede the first of the three rising days.
    prior = rows[:-2]
    peak_index = max(range(len(prior)), key=lambda i: number(prior[i]['high']))
    peak = prior[peak_index]
    later = prior[peak_index + 1:]
    if not later:
        return False, '前期高点之后没有形成可确认的低点', {}
    trough = min(later, key=lambda r: number(r['low']))
    peak_price, low = number(peak['high']), number(trough['low'])
    drawdown = (1 - low / peak_price) * 100
    turned = number(rows[-3]['close']) < number(rows[-2]['close']) < number(rows[-1]['close'])
    quote = bundle.get('quote') or {}
    fresh(quote.get('asOf'), now)
    # Today is on the current (unadjusted) price basis; vendor previous close handles ex-rights.
    turned = turned and number(quote.get('price')) > number(quote.get('previousClose')) > 0
    passed = low < peak_price * Decimal('.8') and turned
    detail = f"高点{peak['date']} → 低点{trough['date']}，回撤{drawdown:.2f}%；最近三天连续上涨{'成立' if turned else '不成立'}"
    return passed, detail, {'peakDate': peak['date'], 'troughDate': trough['date'], 'drawdownPercent': float(drawdown)}


def gains(bundle, now):
    rows = daily_window(bundle, now)
    changes = [number(r.get('changePercent')) for r in rows[-2:]]
    quote = bundle.get('quote') or {}
    fresh(quote.get('asOf'), now)
    price, previous = number(quote.get('price')), number(quote.get('previousClose'))
    if min(price, previous) <= 0:
        raise Missing('今日价格或昨收无效')
    current = (price / previous - 1) * 100
    passed = all(0 < change <= 3 for change in changes) and previous < price <= previous * Decimal('1.03')
    return passed, '前两日/今日涨幅：' + ' / '.join(f'{v:.2f}%' for v in [*changes, current]), {'percentages': [float(v) for v in [*changes, current]]}


def minute_grid(start, end):
    result = []
    point = start
    while point <= end:
        if time(9, 30) <= point.time() <= time(11, 30) or time(13, 1) <= point.time() <= time(15, 0):
            result.append(point.strftime('%H:%M'))
        point += timedelta(minutes=1)
    return result


def comparable_minutes(bundle, now):
    quote = bundle.get('quote') or {}
    quote_time = fresh(quote.get('asOf'), now)
    points = bundle.get('minutes') or []
    today = now.date().isoformat()
    previous = (bundle.get('calendar') or [''])[-1]
    groups = {today: {}, previous: {}}
    for row in points:
        point = timestamp(row.get('time'))
        date, clock = point.date().isoformat(), point.strftime('%H:%M')
        if date not in groups or point > quote_time.replace(second=0, microsecond=0) - timedelta(minutes=1):
            continue
        if clock in groups[date]:
            raise Missing('分钟记录重复，累计量可能重复计算')
        amount = number(row.get('volume'))
        if amount < 0:
            raise Missing('分钟成交量为负')
        groups[date][clock] = amount
    current, yesterday = groups[today], groups[previous]
    if not current or not yesterday:
        raise Missing('缺少今日或前一交易日一分钟成交量')
    cutoff = max(current)
    end = datetime.fromisoformat(f'{today}T{cutoff}:00').replace(tzinfo=CHINA)
    if not (time(9, 31) <= end.time() <= time(11, 30) or time(13, 1) <= end.time() <= time(14, 56)):
        raise Missing('只在连续竞价时段比较已完成的一分钟数据，集合竞价暂不支持')
    reference = now
    if time(11, 30) < now.time() < time(13, 1):
        reference = now.replace(hour=11, minute=30, second=0, microsecond=0)
    if not 0 <= (reference - end).total_seconds() <= 180:
        raise Missing('今日分钟行情过期，不能代表扫描时刻')
    start_clock = min(current)
    if start_clock not in ('09:30', '09:31') or min(yesterday) != start_clock:
        raise Missing('两日开盘分钟口径不同或缺少开盘数据')
    start = end.replace(hour=9, minute=int(start_clock[-2:]))
    expected = set(minute_grid(start, end))
    if set(current) != expected or {k for k in yesterday if k <= cutoff} != expected:
        raise Missing('同一分钟之前的分时数据不完整；不会补零或按全天量估算')
    a = sum(current.values())
    b = sum(yesterday[k] for k in expected)
    if min(a, b) <= 0:
        raise Missing('同刻累计成交量为零或无效')
    return a, b, cutoff


def volume(bundle, now):
    rows = daily_window(bundle, now)
    a, b, c = [number(r['volume']) for r in rows[-3:]]
    current, previous, cutoff = comparable_minutes(bundle, now)
    pairs = [(b, a), (c, b), (current, previous)]
    passed = all(old < new <= old * Decimal('1.5') for new, old in pairs)
    percentages = [(new / old - 1) * 100 for new, old in pairs]
    return passed, '放量增幅：' + ' / '.join(f'{v:.2f}%' for v in percentages) + f'；今日/昨日均截至{cutoff}（单位：手）', {'percentages': [float(v) for v in percentages], 'cutoff': cutoff, 'todayCumulative': float(current), 'previousCumulative': float(previous)}


def earnings(bundle, now):
    report = bundle.get('financial')
    forecasts = bundle.get('forecasts')
    report_valid = False
    financial_unknown = False
    report_period = ''
    try:
        if not report:
            raise Missing('最新正式财报不可用')
        if not report.get('period') or not report.get('announcedAt'):
            raise Missing('财报报告期或公告日期缺失')
        if report['announcedAt'] > now.date().isoformat() or report['period'] > now.date().isoformat():
            raise Missing('财报包含未来日期')
        report_period = report['period']
        net = number(report.get('netProfit'))
        report_valid = net > 0
    except Missing:
        financial_unknown = True
    if report_valid:
        return True, f"最新财报{report_period}归母净利润{net:,.2f}元 > 0；公告{report['announcedAt']}", {'report': report}
    if forecasts is None:
        raise Missing('财报未确认盈利，且正式业绩预告不可用')
    if forecasts:
        # Latest report period and latest announcement supersede all earlier forecasts.
        latest_period = max(f.get('period', '') for f in forecasts)
        current = [f for f in forecasts if f.get('period') == latest_period]
        latest_notice = max(f.get('announcedAt', '') for f in current)
        current = [f for f in current if f.get('announcedAt') == latest_notice]
        for forecast in current:
            if not latest_period or not latest_notice or latest_notice > now.date().isoformat():
                raise Missing('正式预告公告日期或报告期无效')
            if latest_period <= report_period:
                continue  # Already superseded by a formal report.
            if not forecast.get('type'):
                raise Missing('最新正式预告的预告类型缺失')
            if forecast.get('type') == '扭亏' and not forecast.get('metric'):
                raise Missing('扭亏预告缺少对应的盈利指标，无法确认是净利润')
            if forecast.get('type') == '扭亏' and forecast.get('metric') in ('归属于上市公司股东的净利润', '归属于母公司股东的净利润', '净利润'):
                if financial_unknown:
                    raise Missing('最新财报缺失，无法排除该扭亏预告已被后续正式财报覆盖')
                if not forecast.get('official'):
                    raise Missing('扭亏预告未确认来自正式公告数据')
                lower, previous = number(forecast.get('profitLower')), number(forecast.get('previousProfit'))
                if lower > 0 > previous:
                    return True, f'正式扭亏预告{latest_period}，公告{latest_notice}，预计盈利下限{lower:,.2f}元', {'forecast': forecast}
    if financial_unknown:
        raise Missing('最新财报缺失，预告也未能确认有效扭亏')
    return False, f'最新财报{report_period}未盈利，且没有有效正式扭亏预告', {'report': report}


def funds(bundle, now):
    data = bundle.get('funds') or {}
    fresh(data.get('asOf'), now)
    value = number(data.get('netInflow'))
    return value > 0, f'当日主力净流入{value:,.2f}元；主力按供应商大单+超大单口径', {'netInflow': float(value), 'asOf': data['asOf']}


def evaluate(bundle, now):
    now = now.astimezone(CHINA)
    checks = []
    for (key, label), function in zip(RULES, (trend, gains, volume, earnings, funds)):
        try:
            passed, reason, evidence = function(bundle, now)
            check = {'status': 'pass' if passed else 'fail', 'reason': reason, 'evidence': evidence}
        except Missing as error:
            check = {'status': 'unknown', 'reason': str(error) or '必要数据缺失', 'evidence': {}}
        except (KeyError, TypeError, IndexError, AttributeError):
            check = {'status': 'unknown', 'reason': '必要数据字段缺失或结构异常', 'evidence': {}}
        checks.append({'id': key, 'label': label, **check})
    # Missing any necessary input always remains visible, even if another rule fails.
    state = 'unknown' if any(c['status'] == 'unknown' for c in checks) else 'selected' if all(c['status'] == 'pass' for c in checks) else 'rejected'
    quote = bundle.get('quote') or {}
    return {'symbol': bundle['symbol'], 'name': bundle.get('name') or bundle['symbol'],
            'status': state, 'checks': checks, 'evaluatedAt': now.isoformat(),
            'quoteAt': quote.get('asOf'), 'price': quote.get('price'),
            'sources': bundle.get('sources', []), 'errors': bundle.get('errors', [])}
