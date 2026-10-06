"""Validate the real frontend and publish root plus the previous /static/ entry."""
import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from radar.scope import exclusion_reason, POLICY


def verify_scope(row):
    record = dict(row)
    # Formal engine results carry symbol/name; infer only the market from
    # an allowed prefix, then enforce the same collector-side name/code policy.
    if 'exchange' not in record:
        record['exchange'] = '沪' if str(record.get('symbol','')).startswith('6') else '深'
    if exclusion_reason(record):
        raise ValueError('发布结果包含范围外股票：'+str(record.get('symbol')))


def build(output, commit):
    source = ROOT / 'static'
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('必须提供真实的40位Git提交SHA')
    if output.exists():
        raise ValueError('输出目录已存在，请选择新的目录以保留已有文件')
    for name in ('index.html', 'app.js', 'style.css', 'results.json', 'capabilities.json', 'market-calendar.json', 'historical-market.json'):
        if not (source / name).is_file():
            raise ValueError(f'新版必要资源缺失：{name}')
    if (source / 'stocks.json').exists():
        raise ValueError('发布目录仍包含旧版演示行情，停止发布')
    page = (source / 'index.html').read_text()
    script = (source / 'app.js').read_text()
    report = json.loads((source / 'results.json').read_text())
    if 'A股筛选雷达' not in page or '不使用演示行情' not in page:
        raise ValueError('发布目录不是新版真实筛选页面')
    if "fetch('./results.json'" not in script or "fetch('./stocks.json'" in script:
        raise ValueError('前端未读取新版真实结果')
    if report.get('schemaVersion') != 2 or report.get('dataMode') != 'real':
        raise ValueError('结果文件不是新版真实数据结构')
    if not isinstance(report.get('stocks'), list) or not isinstance(report.get('errors'), list):
        raise ValueError('结果文件缺少真实结果或诊断字段')
    for stock in report['stocks']:
        verify_scope(stock)
        checks = stock.get('checks', [])
        if len(checks) != 5 or stock.get('status') not in ('selected', 'rejected', 'unknown'):
            raise ValueError('股票缺少完整五项检查')
        if stock['status'] == 'selected' and any(c.get('status') != 'pass' for c in checks):
            raise ValueError('不能发布必要数据缺失却判为入选的股票')
    history = json.loads((source / 'historical-market.json').read_text())
    if report.get('scopePolicy') != POLICY or history.get('scopePolicy') != POLICY:
        raise ValueError('必须重新生成执行沪深主板非ST排除策略的报告')
    if history.get('dataMode') != 'real' or history.get('historicalOnly') is not True or history.get('formalSelection') is not False:
        raise ValueError('历史候选报告必须与正式入选分离')
    if history.get('candidateCount') != len(history.get('historicalCandidates', [])):
        raise ValueError('历史候选数量不一致')
    for row in history.get('historicalCandidates', []) + history.get('technicalCandidates', []):
        verify_scope(row)
        if row.get('formalSelection') is not False or row.get('status') != 'unknown':
            raise ValueError('历史候选不得正式入选')
        if len(row.get('gains', [])) != 2 or len(row.get('dailyVolumes', [])) != 2 or any(c.get('status') != 'pass' for c in row['gains'] + row['dailyVolumes'] + [row.get('drawdown', {})]):
            raise ValueError('历史候选未完整通过必要历史条件')
    if any(row.get('earnings', {}).get('status') != 'pass' for row in history.get('historicalCandidates', [])):
        raise ValueError('历史候选缺少盈利或正式扭亏核验')
    shutil.copytree(source, output)
    shutil.copytree(source, output / 'static')
    metadata = json.dumps({'commit': commit, 'builtAt': datetime.now(timezone.utc).isoformat(),
                           'frontend': 'real-a-share-v2', 'dataMode': 'real'}, ensure_ascii=False, indent=2) + '\n'
    (output / 'build.json').write_text(metadata)
    (output / 'static/build.json').write_text(metadata)
    print(f'Validated real frontend at / and /static/, commit {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    build(args.output, args.commit)
