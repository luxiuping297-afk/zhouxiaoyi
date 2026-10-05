"""Verified Tencent price/history fallback; never supplies unverified money flow."""
import re
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .historical import parse_bars, verified_change
from .engine import CHINA, Missing
from .provider import Eastmoney, DataError, get_json, numeric, valid_symbol

HISTORY = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
QUOTE = 'https://qt.gtimg.cn/'


def market_code(symbol, index=False):
    return ('sh' if index or symbol.startswith('6') else 'sz') + symbol


def tencent_history(symbol, now, index=False, fetch=get_json):
    if not index:
        valid_symbol(symbol)
        if not symbol.startswith(('6', '0', '3')):
            raise DataError('腾讯备用源尚未验证北交所，不接入')
    code = market_code(symbol, index)
    data = fetch(HISTORY, {'param': f'{code},day,,,160,qfq'}).get('data', {}).get(code, {})
    rows = data.get('day') if index else data.get('qfqday')
    if not isinstance(rows, list) or len(rows) < 121:
        raise DataError('腾讯前复权日线不足121条或字段缺失')
    raw_index = {}
    if not index:
        try:
            raw_data = fetch(HISTORY, {'param': f'{code},day,,,160,'})['data'][code]
            raw_index = {r['date']: r for r in parse_bars(raw_data['day'])}
        except (DataError, Missing, KeyError, TypeError, ValueError):
            pass  # OHLC remains usable; missing raw/ex-rights references never invent gains.
    paired = {r['date']: r for r in parse_bars(rows)}
    output = []
    previous = None
    previous_date = None
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise DataError('腾讯日线字段变化')
        date = datetime.strptime(row[0], '%Y-%m-%d').date().isoformat()
        close, high, low, volume = map(numeric, (row[2], row[3], row[4], row[5]))
        if min(close, high, low) <= 0 or volume < 0 or high < max(close, low):
            raise DataError('腾讯日线价格或成交量无效')
        if date < now.date().isoformat() and previous is not None:
            change = {'status': 'unknown', 'percent': None, 'reason': '缺少同日期不复权对照，无法可靠计算涨幅'}
            if previous_date in raw_index and date in raw_index:
                change = verified_change(paired[previous_date], paired[date], raw_index[previous_date], raw_index[date])
            output.append(dict(date=date, close=close, high=high, low=low, volume=volume,
                               changePercent=change['percent'] if change['status'] != 'unknown' else None,
                               changeVerification=change))
        previous = close
        previous_date = date
    dates = [r['date'] for r in output]
    if dates != sorted(set(dates)):
        raise DataError('腾讯日线日期重复或乱序')
    return output


def tencent_quote(symbol):
    valid_symbol(symbol)
    if not symbol.startswith(('6', '0', '3')):
        raise DataError('腾讯备用报价尚未验证北交所')
    code = market_code(symbol)
    try:
        with urlopen(Request(QUOTE + '?' + urlencode({'q': code}), headers={'User-Agent': 'Mozilla/5.0'}), timeout=12) as response:
            body = response.read().decode('gb18030')
    except (HTTPError, URLError, OSError, UnicodeError):
        raise DataError('腾讯备用报价网络请求失败') from None
    match = re.fullmatch(r'\s*v_' + code + r'="([^"\r\n]+)";\s*', body)
    if not match:
        raise DataError('腾讯报价证券身份或格式变化')
    cells = match[1].split('~')
    if len(cells) < 33 or cells[2] != symbol:
        raise DataError('腾讯报价代码或字段不一致')
    price, previous = numeric(cells[3]), numeric(cells[4])
    if min(price, previous) <= 0:
        raise DataError('腾讯报价价格无效')
    stamp = datetime.strptime(cells[30], '%Y%m%d%H%M%S').replace(tzinfo=CHINA)
    return dict(price=price, previousClose=previous, name=cells[1], asOf=stamp.isoformat())


class VerifiedFallback(Eastmoney):
    name = '东方财富；腾讯已验证日线/报价备用源'

    def calendar(self, now):
        try:
            value = super().calendar(now)
            self.calendar_url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
            return value
        except DataError:
            rows = tencent_history('000001', now, index=True)
            self.calendar_url = HISTORY
            if len(rows) < 120:
                raise DataError('备用指数日线不足120个交易日')
            return [r['date'] for r in rows][-120:]

    def collect(self, symbol, calendar):
        bundle = super().collect(symbol, calendar)
        # Calendar provenance is independently identified; do not claim Eastmoney success.
        for source in bundle['sources']:
            if source['kind'] == 'calendar':
                source.update(name='指数日线交易日（东方财富优先，腾讯备用）', url=getattr(self, 'calendar_url', HISTORY))
        for kind, operation, url in (
            ('history', lambda: tencent_history(symbol, datetime.now(CHINA)), HISTORY),
            ('quote', lambda: tencent_quote(symbol), QUOTE),
        ):
            if kind in bundle:
                continue
            source = dict(kind=kind, name='腾讯前复权日线；涨幅经同日期原价及精度区间核验计算' if kind == 'history' else '腾讯报价', url=url)
            try:
                value = operation()
                bundle[kind] = value
                if kind == 'history' and any(row.get('changePercent') is None for row in value[-2:]):
                    bundle['errors'].append(dict(kind='history', message='前两日涨幅缺少可靠复权/原价对照或跨越舍入边界，无法判断；不以复权价相除直接替代严格阈值'))
                source.update(status='available', dataAt=value[-1]['date'] if kind == 'history' else value['asOf'])
                if kind == 'quote':
                    bundle['name'] = value['name']
                    bundle['funds'] = None
                    bundle['errors'].append(dict(kind='funds', message='东方财富盘中资金请求失败；腾讯主力字段和时间戳未验证，不使用报价代替资金'))
                    bundle['sources'].append(dict(kind='funds', name='东方财富盘中主力资金', url='https://push2.eastmoney.com/api/qt/clist/get',
                        status='unavailable', fetchedAt=datetime.now(CHINA).isoformat()))
            except (DataError, ValueError, KeyError, TypeError) as error:
                source['status'] = 'unavailable'
                bundle['errors'].append(dict(kind=kind, message=str(error)))
            source['fetchedAt'] = datetime.now(CHINA).isoformat()
            bundle['sources'].append(source)
        return bundle
