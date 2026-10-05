"""Validate the real frontend and publish root plus the previous /static/ entry."""
import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output, commit):
    source = ROOT / 'static'
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('必须提供真实的40位Git提交SHA')
    if output.exists():
        raise ValueError('输出目录已存在，请选择新的目录以保留已有文件')
    for name in ('index.html', 'app.js', 'style.css', 'results.json', 'capabilities.json', 'market-calendar.json'):
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
        checks = stock.get('checks', [])
        if len(checks) != 5 or stock.get('status') not in ('selected', 'rejected', 'unknown'):
            raise ValueError('股票缺少完整五项检查')
        if stock['status'] == 'selected' and any(c.get('status') != 'pass' for c in checks):
            raise ValueError('不能发布必要数据缺失却判为入选的股票')
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
