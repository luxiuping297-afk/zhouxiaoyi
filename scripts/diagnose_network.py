"""Small, read-only connectivity matrix. Does not generate screening selections."""
import argparse
import concurrent.futures
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from radar.engine import CHINA
from radar.provider import HOSTS, secid, valid_symbol


def failure_kind(status, body):
    if status == 503 and b'upstream connect error' in body and b'connection termination' in body:
        return 'upstream_connection_terminated', '上游连接在响应头之前被终止，未收到行情JSON'
    if status == 502 and b'Bad Gateway' in body:
        return 'upstream_bad_gateway', '上游网关返回502，未收到行情JSON'
    return 'http_error', f'HTTP {status}，未确认数据可获取'


def examine(name, url, params, symbol, timeout=12):
    record = {'interface': name, 'symbol': symbol, 'url': url, 'requestedAt': datetime.now(CHINA).isoformat(),
              'httpStatus': None, 'status': 'unavailable', 'records': None, 'latestDataAt': None}
    start = time.monotonic()
    try:
        request = Request(url + '?' + urlencode(params), headers={
            'User-Agent': 'Mozilla/5.0', 'Accept': '*/*', 'Referer': 'https://quote.eastmoney.com/'})
        with urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000)
            record.update(httpStatus=response.status, server=response.headers.get('Server'),
                          contentType=response.headers.get('Content-Type'))
        if name == 'tencent_quote':
            text = body.decode('gb18030')
            prefix = 'sh' if symbol.startswith('6') else 'bj' if symbol.startswith(('4', '8', '9')) else 'sz'
            expected = 'v_' + prefix + symbol + '="'
            if not text.startswith(expected):
                raise ValueError('行情证券身份不匹配')
            fields = text.split('"', 2)[1].split('~')
            if len(fields) < 33 or fields[2] != symbol:
                raise ValueError('行情字段或证券代码不匹配')
            point = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=CHINA)
            record.update(records=1, latestDataAt=point.isoformat())
        elif name == 'tencent_funds':
            # No unverified positions or dates are treated as current main money flow.
            record.update(kind='unverified_funds_schema', message='响应已收到，但未验证主力定义、字段及独立数据时间戳；不能接入筛选')
            return record
        else:
            payload = json.loads(body)
            if name.startswith('tencent_history'):
                prefix = 'sh' if symbol.startswith('6') else 'bj' if symbol.startswith(('4', '8', '9')) else 'sz'
                data = payload.get('data', {}).get(prefix + symbol, {})
                rows = data.get('qfqday')
                if not isinstance(rows, list) or len(rows) < 121:
                    raise ValueError('前复权日线不足121条或字段缺失')
                record.update(records=len(rows), latestDataAt=max(row[0] for row in rows))
            elif name in ('financial', 'forecasts'):
                result = payload.get('result')
                if payload.get('success') is not True or not isinstance(result, dict) or not isinstance(result.get('data'), list):
                    raise ValueError('财报/预告结构无效，不能确认无记录')
                rows = result['data']
                record['records'] = len(rows)
                if rows:
                    key = 'UPDATE_DATE' if name == 'financial' else 'NOTICE_DATE'
                    record['latestDataAt'] = max(str(row.get(key, '')) for row in rows)
            else:
                data = payload.get('data')
                if not isinstance(data, dict):
                    raise ValueError('行情响应data为空或格式变化')
                if name.startswith('history'):
                    rows = data.get('klines')
                    if data.get('code') != symbol or not isinstance(rows, list) or len(rows) < 121:
                        raise ValueError('日线证券身份错误或不足121条')
                    record.update(records=len(rows), latestDataAt=max(r.split(',')[0] for r in rows))
                elif name == 'minutes':
                    rows = data.get('trends')
                    if data.get('code') != symbol or not isinstance(rows, list) or not rows:
                        raise ValueError('一分钟记录为空或身份不匹配')
                    record.update(records=len(rows), latestDataAt=max(r.split(',')[0] for r in rows))
                else:
                    rows = data.get('diff')
                    if isinstance(rows, dict):
                        rows = list(rows.values())
                    if not isinstance(rows, list) or not rows:
                        raise ValueError('盘中资金和行情记录为空')
                    row = next((r for r in rows if r.get('f12') == symbol), None)
                    if not row or row.get('f62') in (None, '-', '') or not row.get('f124'):
                        raise ValueError('缺少主力资金字段、行情时间戳或对应证券')
                    point = datetime.fromtimestamp(float(row['f124']), CHINA)
                    record.update(records=1, latestDataAt=point.isoformat())
        record.update(status='reachable', kind='data_received', message='请求及基本字段通过；不代表当日盘中链路通过')
    except HTTPError as error:
        record['httpStatus'] = error.code
        record['server'] = error.headers.get('Server')
        record['contentType'] = error.headers.get('Content-Type')
        kind, message = failure_kind(error.code, error.read(4000))
        record.update(kind=kind, message=message)
    except URLError as error:
        is_policy = 'Tunnel connection failed: 403' in str(error.reason)
        record.update(kind='proxy_policy_denied' if is_policy else 'network_error',
                      message='网络代理拒绝CONNECT请求（403），目标接口尚未收到请求' if is_policy else '连接错误或超时')
    except (ValueError, KeyError, TypeError, IndexError, OverflowError, UnicodeError):
        record.update(kind='invalid_data', message='已收到响应，但必要字段、证券身份或数据范围未通过验证')
    except (OSError, TimeoutError):
        record.update(kind='network_error', message='网络连接失败或超时')
    finally:
        record['elapsedMs'] = round((time.monotonic() - start) * 1000)
    return record


def diagnose(symbols, context):
    requests = []
    for symbol in symbols:
        history = {'secid': secid(symbol), 'klt': 101, 'fqt': 1, 'lmt': 160, 'beg': 0, 'end': 20500101,
                   'ut': '7eea3edcaed734bea9cbfc24409ed989', 'fields1': 'f1,f2,f3,f4,f5,f6',
                   'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'}
        quote = {'fs': 'i:' + secid(symbol), 'fltt': 2, 'invt': 2, 'pn': 1, 'pz': 10,
                 'fields': 'f2,f12,f13,f14,f18,f62,f124', 'ut': 'bd1d9ddb04089700cf9c27f6f7426281'}
        prefix = 'sh' if symbol.startswith('6') else 'bj' if symbol.startswith(('4', '8', '9')) else 'sz'
        requests += [('history', HOSTS['history'], history, symbol),
                     ('history_33', HOSTS['history'].replace('push2his.', '33.push2his.'), history, symbol),
                     ('funds', HOSTS['quote'], quote, symbol),
                     ('funds_82', HOSTS['quote'].replace('push2.', '82.push2.'), quote, symbol),
                     ('minutes', HOSTS['minutes'], {'secid': secid(symbol), 'ndays': 5,
                      'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8', 'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58'}, symbol),
                     ('tencent_history', 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',
                      {'param': prefix + symbol + ',day,,,160,qfq'}, symbol),
                     ('tencent_history_old', 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
                      {'param': prefix + symbol + ',day,,,160,qfq'}, symbol),
                     ('tencent_quote', 'https://qt.gtimg.cn/', {'q': prefix + symbol}, symbol),
                     ('tencent_funds', 'https://qt.gtimg.cn/', {'q': 'ff_' + prefix + symbol}, symbol)]
        for kind, report, period, notice in [('financial', 'RPT_LICO_FN_CPD', 'REPORTDATE', 'UPDATE_DATE'),
                                             ('forecasts', 'RPT_PUBLIC_OP_NEWPREDICT', 'REPORT_DATE', 'NOTICE_DATE')]:
            requests.append((kind, HOSTS[kind], {'reportName': report, 'columns': 'ALL',
                'filter': f'(SECURITY_CODE="{symbol}")', 'pageSize': 10, 'pageNumber': 1,
                'sortColumns': period + ',' + notice, 'sortTypes': '-1,-1'}, symbol))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda args: examine(*args), requests))
    return {'checkedAt': datetime.now(CHINA).isoformat(), 'context': context, 'symbols': symbols,
            'stage': 'connectivity_only', 'liveChainVerified': False,
            'note': '连接和历史记录校验不等于盘中筛选通过；不生成入选股票，不启动全市场扫描。',
            'proxyConfigured': any(os.environ.get(k) for k in ('HTTPS_PROXY', 'https_proxy')),
            'checks': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbols', default='600519,000001,300750')
    parser.add_argument('--context', default='cloud')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    symbols = [valid_symbol(s.strip()) for s in args.symbols.split(',')]
    if not 1 <= len(symbols) <= 5:
        parser.error('诊断仅允许1至5只股票')
    result = diagnose(symbols, args.context)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
