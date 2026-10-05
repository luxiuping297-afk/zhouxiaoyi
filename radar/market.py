"""Exchange holiday state, independent of quote freshness and network health."""
import json
from datetime import timedelta, time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo


@lru_cache(maxsize=1)
def calendar_data():
    try:
        return json.loads((Path(__file__).resolve().parents[1] / 'static/market-calendar.json').read_text())
    except (OSError, ValueError):
        return {'years': {}}


def trading_day(day, calendar):
    year = calendar.get('years', {}).get(str(day.year))
    if not year:
        return None
    return day.weekday() < 5 and not any(h['start'] <= day.isoformat() <= h['end'] for h in year['holidays'])


def market_status(now, calendar=None):
    now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    calendar = calendar if calendar is not None else calendar_data()
    year = calendar.get('years', {}).get(str(now.year))
    result = {'checkedAt': now.isoformat(), 'timeZone': 'Asia/Shanghai', 'source': year['source'] if year else None,
              'state': 'unknown', 'message': '交易所日历未覆盖当前年份，无法确认交易状态',
              'lastTradingDate': None, 'nextTradingDate': None}
    if not year:
        return result
    day = now.date()
    for delta in range(1, 22):
        previous = day - timedelta(days=delta)
        if trading_day(previous, calendar):
            result['lastTradingDate'] = previous.isoformat()
            break
    for delta in range(1, 22):
        next_day = day + timedelta(days=delta)
        if trading_day(next_day, calendar):
            result['nextTradingDate'] = next_day.isoformat()
            break
    if not trading_day(day, calendar):
        holiday = next((h['name'] for h in year['holidays'] if h['start'] <= day.isoformat() <= h['end']), '周末')
        result.update(state='closed', message='休市，等待下一交易日', reason=holiday)
    elif time(9, 30) <= now.time() <= time(11, 30) or time(13) <= now.time() <= time(15):
        result.update(state='open', message='交易时段；仍须校验全部五项条件和数据时效')
    elif time(11, 30) < now.time() < time(13):
        result.update(state='break', message='午间休息，等待下午交易时段')
    elif now.time() < time(9, 30):
        result.update(state='preopen', message='尚未开盘，等待今日交易时段')
    else:
        result.update(state='closed', message='休市，等待下一交易日', reason='今日已收盘', lastTradingDate=day.isoformat())
    return result
