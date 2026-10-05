"""Check every required candidate endpoint before running a broad scan."""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from radar.engine import CHINA
from radar.provider import DataError, Eastmoney, HOSTS


def probe(provider):
    now = datetime.now(CHINA)
    symbol = '600519'  # Connectivity check only, never a fabricated selection.
    operations = {
        'history': lambda: len(provider.history(symbol, now)),
        'minutes': lambda: len(provider.minutes(symbol)),
        'financial': lambda: bool(provider.reports('financial', symbol, now)),
        'forecasts': lambda: len(provider.reports('forecasts', symbol, now)),
        'funds': lambda: provider.quote(symbol)[1],
    }
    checks = []
    for kind, operation in operations.items():
        try:
            value = operation()
            if kind == 'funds' and value is None:
                raise ValueError('主力净流入字段缺失')
            if kind == 'history' and value < 120:
                raise ValueError('日线不足120条')
            if kind == 'minutes' and not value:
                raise ValueError('分钟记录为空')
            if kind == 'financial' and not value:
                raise ValueError('财报记录为空')
            check = {'status': 'reachable', 'message': '请求和基本字段解析通过；不代表盘中完整性或全市场授权已确认'}
        except (DataError, ValueError, TypeError, KeyError, OverflowError) as error:
            check = {'status': 'unavailable', 'message': str(error)}
            if kind == 'funds':
                try:
                    historical = provider.historical_funds(symbol)
                    check = {'status': 'partial', 'message': f"资金日线可获取，最新{historical['tradeDate']}；扫描时刻盘中资金未确认：{error}",
                             'historicalSource': HOSTS['funds_history'], 'historicalEvidence': historical}
                except (DataError, ValueError, TypeError, KeyError, OverflowError):
                    pass
        checks.append({'kind': kind, 'source': HOSTS['quote' if kind == 'funds' else kind], **check})
    return {'checkedAt': now.isoformat(), 'sampleSymbol': symbol, 'checks': checks}


if __name__ == '__main__':
    report = probe(Eastmoney())
    destination = ROOT / 'static/capabilities.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if all(c['status'] == 'reachable' for c in report['checks']) else 2)
