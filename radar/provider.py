"""Candidate Eastmoney adapters based on public AKShare documentation.

No credential is required by these web endpoints. Availability is checked at runtime;
network denial, changed fields, nulls and incomplete pages are errors, never defaults.
"""
import json
import math
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .engine import CHINA, Missing, number

HOSTS = {
    'history': 'https://push2his.eastmoney.com/api/qt/stock/kline/get',
    'minutes': 'https://push2his.eastmoney.com/api/qt/stock/trends2/get',
    'quote': 'https://push2.eastmoney.com/api/qt/clist/get',
    'funds_history': 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get',
    'universe': 'https://push2.eastmoney.com/api/qt/clist/get',
    'financial': 'https://datacenter-web.eastmoney.com/api/data/v1/get',
    'forecasts': 'https://datacenter-web.eastmoney.com/api/data/v1/get',
}


class DataError(ValueError):
    pass


def numeric(value):
    try:
        result = float(number(value))
        if not math.isfinite(result):
            raise Missing('必要数值超出支持范围')
        return result
    except Missing as error:
        raise DataError(str(error)) from None


def valid_symbol(symbol):
    if not re.fullmatch(r'(?:60|68|00|30|43|83|87|88|92)\d{4}', symbol):
        raise DataError('需要沪深京A股六位代码（不支持指数、基金或B股）')
    return symbol


def secid(symbol):
    valid_symbol(symbol)
    return ('1.' if symbol.startswith('6') else '0.') + symbol


def get_json(url, params, timeout=12):
    request = Request(url + '?' + urlencode(params), headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise DataError(f'HTTP {response.status}')
            payload = json.load(response)
    except HTTPError as error:
        body = error.read(4000).decode('utf-8', errors='replace')
        reason = ('上游连接在响应头之前被终止，未收到行情JSON' if error.code == 503 and 'connection termination' in body
                  else '上游网关返回502，未收到行情JSON' if error.code == 502 and 'Bad Gateway' in body
                  else '接口返回HTTP错误，未取得有效数据')
        raise DataError(f'HTTP {error.code}：{reason}') from None
    except URLError as error:
        # Do not include proxy URLs, credentials or potentially sensitive server responses.
        reason = str(error.reason)
        message = '网络代理403拒绝（域名未放行或访问策略拒绝）' if '403' in reason else '接口网络请求失败'
        raise DataError(message) from None
    except (TimeoutError, OSError):
        raise DataError('接口超时或网络不可用') from None
    except (ValueError, UnicodeError):
        raise DataError('接口未返回有效JSON') from None
    if not isinstance(payload, dict):
        raise DataError('接口顶层格式变化')
    return payload


class Eastmoney:
    name = '东方财富公开网页接口（非承诺服务）'

    def __init__(self, fetch=get_json):
        self.fetch = fetch

    def history(self, symbol, now, *, index=False):
        params = {'secid': '1.000001' if index else secid(symbol), 'klt': 101, 'fqt': 0 if index else 1,
                  'ut': '7eea3edcaed734bea9cbfc24409ed989',
                  'lmt': 160, 'beg': 0, 'end': now.strftime('%Y%m%d'),
                  'fields1': 'f1,f2,f3,f4,f5,f6',
                  'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'}
        payload = self.fetch(HOSTS['history'], params)
        data = payload.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('klines'), list) or not data['klines']:
            raise DataError('日线接口没有有效记录')
        expected_market = 1 if index or symbol.startswith('6') else 0
        if data.get('code') != symbol or data.get('market') != expected_market:
            raise DataError('日线返回的证券代码或市场不一致')
        rows = []
        for line in data['klines']:
            cells = line.split(',')
            if len(cells) < 9:
                raise DataError('日线字段结构变化')
            date = datetime.strptime(cells[0], '%Y-%m-%d').date().isoformat()
            if date >= now.date().isoformat():
                continue
            rows.append({'date': date, 'close': numeric(cells[2]), 'high': numeric(cells[3]),
                         'low': numeric(cells[4]), 'volume': numeric(cells[5]), 'changePercent': numeric(cells[8])})
        return rows

    def calendar(self, now):
        # Past market sessions inferred from index daily bars; missing index data is fatal.
        rows = self.history('000001', now, index=True)
        dates = [row['date'] for row in rows]
        if len(dates) < 120 or dates != sorted(set(dates)):
            raise DataError('指数日线不足以确定120个已完成交易日')
        return dates[-120:]

    def quote(self, symbol):
        # Use clist's documented f2/f18 price and f62 main-inflow fields, not
        # similarly numbered stock/get fields with a potentially different meaning.
        payload = self.fetch(HOSTS['quote'], {'fs': 'i:' + secid(symbol), 'fltt': 2, 'invt': 2,
                                            'pn': 1, 'pz': 10, 'np': 1, 'fid': 'f12',
                                            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                                            'fields': 'f2,f12,f13,f14,f18,f62,f124'})
        data = payload.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('diff'), (dict, list)):
            raise DataError('行情接口记录缺失或字段变化')
        records = data['diff']
        if isinstance(records, dict):
            records = list(records.values())
        matches = [r for r in records if r.get('f12') == symbol]
        if len(matches) != 1:
            raise DataError('行情接口代码不一致或无数据')
        data = matches[0]
        if data.get('f13') != (1 if symbol.startswith('6') else 0):
            raise DataError('当前行情返回的证券市场不一致')
        epoch = numeric(data.get('f124'))
        if epoch <= 0:
            raise DataError('行情更新时间无效')
        as_of = datetime.fromtimestamp(epoch, CHINA).isoformat()
        price, previous = numeric(data.get('f2')), numeric(data.get('f18'))
        if min(price, previous) <= 0:
            raise DataError('最新价格或昨收无效（可能停牌）')
        # Keep funds independently missing if quote fields are valid but f62 is absent.
        try:
            funds = {'netInflow': numeric(data.get('f62')), 'asOf': as_of}
        except DataError:
            funds = None
        return {'price': price, 'previousClose': previous, 'asOf': as_of, 'name': data.get('f14')}, funds

    def historical_funds(self, symbol):
        """Diagnostic only: daily money flow cannot replace timed intraday money flow."""
        payload = self.fetch(HOSTS['funds_history'], {'secid': secid(symbol), 'lmt': 5, 'klt': 101,
            'fields1': 'f1,f2,f3,f7', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
            'ut': 'b2884a393a59ad64002292a3e90d46a5'})
        data = payload.get('data')
        if not isinstance(data, dict) or data.get('code') != symbol or not data.get('klines'):
            raise DataError('资金日线缺失或代码不一致')
        cells = data['klines'][-1].split(',')
        if len(cells) < 2:
            raise DataError('资金日线字段结构变化')
        return {'tradeDate': datetime.strptime(cells[0], '%Y-%m-%d').date().isoformat(),
                'netInflow': numeric(cells[1])}

    def minutes(self, symbol):
        payload = self.fetch(HOSTS['minutes'], {'secid': secid(symbol), 'ndays': 5, 'iscr': 0,
                                              'ut': '7eea3edcaed734bea9cbfc24409ed989',
                                              'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
                                              'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58'})
        data = payload.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('trends'), list) or not data['trends']:
            raise DataError('分钟接口没有有效记录')
        if data.get('code') != symbol or data.get('market') != (1 if symbol.startswith('6') else 0):
            raise DataError('分钟返回的证券代码或市场不一致')
        rows = []
        for line in data['trends']:
            cells = line.split(',')
            if len(cells) != 8:
                raise DataError('一分钟字段结构变化')
            point = datetime.strptime(cells[0], '%Y-%m-%d %H:%M').replace(tzinfo=CHINA)
            rows.append({'time': point.isoformat(), 'volume': numeric(cells[5])})
        return rows

    def reports(self, kind, symbol, now):
        forecast = kind == 'forecasts'
        report = 'RPT_PUBLIC_OP_NEWPREDICT' if forecast else 'RPT_LICO_FN_CPD'
        period = 'REPORT_DATE' if forecast else 'REPORTDATE'
        notice = 'NOTICE_DATE' if forecast else 'UPDATE_DATE'
        params = {'reportName': report, 'columns': 'ALL', 'filter': f'(SECURITY_CODE="{valid_symbol(symbol)}")',
                  'pageSize': 100, 'pageNumber': 1, 'sortColumns': f'{period},{notice}', 'sortTypes': '-1,-1'}
        payload = self.fetch(HOSTS[kind], params)
        if payload.get('success') is not True:
            raise DataError(f'{kind}接口未确认请求成功（不会视为无预告）')
        result = payload.get('result')
        if result is None:
            raise DataError(f'{kind}结果缺失，无法确认是否无记录')
        if not isinstance(result, dict) or not isinstance(result.get('data'), list):
            raise DataError(f'{kind}记录格式变化')
        records = result['data']
        if not records:
            if result.get('count') == 0:
                return [] if forecast else None
            raise DataError(f'{kind}接口空数据但总记录数不为零')
        usable = []
        for row in records:
            if row.get('SECURITY_CODE') != symbol or not row.get(period) or not row.get(notice):
                raise DataError(f'{kind}代码、报告期或公告日期缺失')
            report_date = str(row[period])[:10]
            announced = str(row[notice])[:10]
            datetime.strptime(report_date, '%Y-%m-%d')
            datetime.strptime(announced, '%Y-%m-%d')
            if announced <= now.date().isoformat():
                usable.append(row)
        if not usable:
            raise DataError(f'{kind}没有扫描时刻已公布的有效记录')
        # Ensure latest period's rows are not cut off by pagination.
        usable.sort(key=lambda row: (row[period], row[notice]), reverse=True)
        if result.get('pages', 1) > 1 and usable[-1][period] == usable[0][period]:
            raise DataError('最新报告期记录被分页截断')
        if not forecast:
            row = usable[0]
            return {'period': str(row[period])[:10], 'announcedAt': str(row[notice])[:10],
                    'netProfit': numeric(row.get('PARENT_NETPROFIT')), 'metric': '归母净利润'}
        latest_period = usable[0][period]
        return [{'period': str(row[period])[:10], 'announcedAt': str(row[notice])[:10],
                 'type': row.get('PREDICT_TYPE'), 'metric': row.get('PREDICT_FINANCE'),
                 'profitLower': row.get('PREDICT_AMT_LOWER'), 'previousProfit': row.get('PREYEAR_SAME_PERIOD'),
                 'official': True} for row in usable if row[period] == latest_period]

    def universe(self):
        result, identities, expected = [], set(), None
        for page in range(1, 101):
            payload = self.fetch(HOSTS['universe'], {'pn': page, 'pz': 100, 'po': 0, 'np': 1,
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': 2, 'invt': 2, 'fid': 'f12',
                'fs': 'm:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048', 'fields': 'f12,f13,f14'})
            data = payload.get('data')
            if not isinstance(data, dict) or not isinstance(data.get('diff'), (list, dict)):
                raise DataError('A股证券列表数据缺失')
            total = int(data.get('total', 0))
            if expected is None:
                expected = total
            if expected <= 0 or expected != total:
                raise DataError('A股列表为空或分页期间总数变化')
            records = data['diff']
            if isinstance(records, dict):
                records = list(records.values())
            if not records:
                raise DataError('A股列表分页不完整')
            for record in records:
                symbol = valid_symbol(record.get('f12', ''))
                if symbol in identities:
                    raise DataError('A股列表分页重复，不能声称全市场扫描')
                identities.add(symbol)
                result.append(symbol)
            if len(result) == expected:
                return result
            if len(result) > expected:
                raise DataError('A股列表数量超过声明总数')
        raise DataError('A股列表分页超出安全上限，列表未完成')

    def collect(self, symbol, calendar):
        bundle = {'symbol': symbol, 'calendar': calendar, 'errors': [], 'sources': []}
        if calendar:
            bundle['sources'].append({'kind': 'calendar', 'name': '上证指数日线推导已完成交易日',
                'url': HOSTS['history'], 'status': 'available', 'dataAt': calendar[-1],
                'fetchedAt': datetime.now(CHINA).isoformat()})
        operations = [('history', lambda: self.history(symbol, datetime.now(CHINA))),
                      ('minutes', lambda: self.minutes(symbol)),
                      ('financial', lambda: self.reports('financial', symbol, datetime.now(CHINA))),
                      ('forecasts', lambda: self.reports('forecasts', symbol, datetime.now(CHINA))),
                      ('quote', lambda: self.quote(symbol))]
        for kind, operation in operations:
            source = {'kind': kind, 'name': self.name, 'url': HOSTS[kind]}
            try:
                value = operation()
                if kind == 'quote':
                    bundle['quote'], bundle['funds'] = value
                    bundle['name'] = value[0].get('name')
                    source['dataAt'] = value[0]['asOf']
                    if value[1] is None:
                        bundle['errors'].append({'kind': 'funds', 'message': '主力净流入字段f62缺失'})
                    bundle['sources'].append({'kind': 'funds', 'name': self.name + ' clist字段f62（大单+超大单）',
                        'url': HOSTS['quote'], 'status': 'available' if value[1] else 'unavailable',
                        'dataAt': value[0]['asOf'], 'fetchedAt': datetime.now(CHINA).isoformat()})
                else:
                    bundle[kind] = value
                    if kind == 'history' and value:
                        source['dataAt'] = max(row['date'] for row in value)
                    elif kind == 'minutes' and value:
                        source['dataAt'] = max(row['time'] for row in value)
                    elif kind == 'financial' and value:
                        source['dataAt'] = value['announcedAt']
                    elif kind == 'forecasts' and value:
                        source['dataAt'] = max(row['announcedAt'] for row in value)
                source['status'] = 'available'
            except (DataError, ValueError, KeyError, TypeError, OverflowError) as error:
                source['status'] = 'unavailable'
                bundle['errors'].append({'kind': kind, 'message': str(error)})
            source['fetchedAt'] = datetime.now(CHINA).isoformat()
            bundle['sources'].append(source)
        return bundle
