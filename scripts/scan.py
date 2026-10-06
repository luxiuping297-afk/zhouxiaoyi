"""Collect real data and atomically publish a fail-closed static snapshot."""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from radar.engine import CHINA, evaluate
from radar.provider import DataError, Eastmoney, valid_symbol
from radar.fallback import VerifiedFallback
from radar.market import market_status
from radar.universe import universe
from radar.scope import restrict, exclusion_reason, SCOPE, POLICY


def scan(provider, symbols=None, workers=2, limit=None, capabilities=None, listing=None):
    explicit = symbols is not None
    started = datetime.now(CHINA)
    report = {'schemaVersion': 2, 'scanStartedAt': started.isoformat(), 'generatedAt': None,
              'validForSeconds': 180, 'scope': SCOPE+('（指定代码）' if symbols is not None else ''), 'scopePolicy': POLICY,
              'universeCount': None, 'scannedCount': 0, 'complete': False, 'stocks': [], 'errors': [],
              'dataMode': 'real', 'provider': provider.name}
    report['marketStatus'] = market_status(started)
    if report['marketStatus']['state'] != 'open':
        report.update(generatedAt=started.isoformat(), liveChainVerified=False,
                      scope='当前市场状态（未启动盘中筛选）',
                      counts=dict(selected=0, rejected=0, unknown=0, expired=0))
        return report
    try:
        listing = listing if listing is not None else universe(provider.fetch)
        eligible, scope_stats = restrict(listing['stocks'])
        report.update(scope_stats)
        if explicit:report['scope'] += '（指定代码）'
        report.update(universeSource=listing['source'], universeFetchedAt=listing['fetchedAt'])
    except (DataError, ValueError, KeyError, TypeError) as error:
        report.update(generatedAt=started.isoformat(), liveChainVerified=False,
                      counts=dict(selected=0, rejected=0, unknown=0, expired=0))
        report['errors'].append(f'无法确认主板及ST排除范围：{error}；未请求个股数据')
        return report
    identities = {r['symbol']: r for r in eligible}
    if explicit:
        report['requestedCount'] = len(symbols)
        report['excludedRequestedSymbols'] = [s for s in symbols if s not in identities]
        symbols = [s for s in symbols if s in identities]
    if not explicit:
        sample_symbols = [s for s in ('600519', '000001', '600036') if s in identities]
        if len(sample_symbols) != 3:
            report.update(generatedAt=started.isoformat(), counts=dict(selected=0,rejected=0,unknown=0,expired=0))
            report['errors'].append('主板链路验证样本身份不可确认，未启动批量请求')
            return report
        sample = scan(provider, sample_symbols, workers, listing=listing)
        if sample['errors'] or any(any(c['status'] == 'unknown' for c in row['checks']) for row in sample['stocks']):
            sample['scope'] = '三只真实股票链路验证（未启动全市场扫描）'
            sample['complete'] = False
            sample['liveChainVerified'] = False
            sample['errors'].append('样本链路存在无法判断项；暂停全市场扫描。')
            return sample
    try:
        calendar = provider.calendar(started)
    except (DataError, ValueError) as error:
        calendar = []
        report['errors'].append(f'交易日历不可用：{error}')
    if symbols is None:
        symbols = list(identities)
    report['universeCount'] = len(symbols) if symbols or not any('证券列表不可用' in e for e in report['errors']) else None
    if limit is not None and len(symbols) > limit:
        symbols = symbols[:limit]
        report['scope'] += f'（仅前{limit}只，非全量）'
    # Avoid thousands of doomed requests when the shared prerequisite is missing.
    if not calendar and not explicit:
        for symbol in symbols:
            bundle = {'symbol': symbol, 'name': identities[symbol]['name'], 'errors': [{'kind': 'calendar', 'message': '交易日历不可用，未请求个股数据'}]}
            report['stocks'].append(evaluate(bundle, datetime.now(CHINA)))
    else:
        def one(symbol):
            bundle = provider.collect(symbol, calendar)
            current_name = bundle.get('name') or (bundle.get('quote') or {}).get('name')
            quote_name = (bundle.get('quote') or {}).get('name')
            if any(exclusion_reason(dict(identities[symbol], name=name)) for name in (current_name, quote_name) if name):
                return None  # New ST designation since listing: never evaluate/select.
            bundle['name'] = current_name or identities[symbol]['name']
            return evaluate(bundle, datetime.now(CHINA))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for row in pool.map(one, symbols):
                if row is None:
                    report['errors'].append('扫描期间证券名称变为ST/*ST，已排除，不列为正式结果')
                    continue
                report['stocks'].append(row)
                print(f"{row['symbol']} {row['status']}", file=sys.stderr, flush=True)
    report['scannedCount'] = len(report['stocks'])
    report['liveChainVerified'] = bool(report['stocks']) and not any(c['status'] == 'unknown' for row in report['stocks'] for c in row['checks'])
    report['complete'] = bool(symbols) and not report['errors'] and report['scannedCount'] == report['universeCount'] and report['liveChainVerified']
    finished = datetime.now(CHINA)
    report['generatedAt'] = finished.isoformat()
    report['counts'] = {status: sum(row['status'] == status for row in report['stocks']) for status in ('selected', 'rejected', 'unknown')}
    report['counts']['expired'] = sum((finished - datetime.fromisoformat(row['evaluatedAt'])).total_seconds() > 180 for row in report['stocks'])
    return report


def main():
    parser = argparse.ArgumentParser(description='真实A股扫描；数据缺失时输出无法判断，不使用演示数据')
    parser.add_argument('--symbols', help='六位代码逗号分隔；只采集沪深主板非ST，指定代码也不能绕过排除')
    parser.add_argument('--limit', type=int, help='只扫描前N只；结果明确标注局部范围')
    parser.add_argument('--workers', type=int, default=2, choices=range(1, 5))
    parser.add_argument('--preflight', action='store_true', help='先实测五类接口，失败时只发布诊断，不做批量采集')
    parser.add_argument('--output', type=Path, default=ROOT / 'static/results.json')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit 必须大于0')
    try:
        symbols = list(dict.fromkeys(valid_symbol(s.strip()) for s in args.symbols.split(','))) if args.symbols else None
    except DataError as error:
        parser.error(str(error))
    capabilities = None
    if args.preflight and market_status(datetime.now(CHINA))['state'] == 'open':
        from scripts.probe import probe
        capabilities = probe(VerifiedFallback())
        (ROOT / 'static/capabilities.json').write_text(json.dumps(capabilities, ensure_ascii=False, indent=2) + '\n')
    report = scan(VerifiedFallback(), symbols, args.workers, args.limit, capabilities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(args.output)
    print(json.dumps({'marketState': report['marketStatus']['state'], 'complete': report['complete'], 'counts': report['counts'], 'errors': report['errors']}, ensure_ascii=False))
    if report['marketStatus']['state'] in ('closed', 'preopen', 'break'):
        return 0  # Normal pause, not an interface failure or successful live screening.
    return 0 if report['complete'] and not report['counts']['unknown'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
