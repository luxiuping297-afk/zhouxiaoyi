"""Publish only date-locked after-close results; reject legacy intraday reports."""
import argparse,json,re,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from radar.scope import exclusion_reason,POLICY
from radar.after_close import session_dates


def build(output,commit):
    source=ROOT/'static'
    if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('必须提供真实40位提交SHA')
    if output.exists():raise ValueError('输出目录已存在')
    required=('index.html','app.js','style.css','results.json','market-calendar.json')
    for name in required:
        if not (source/name).is_file():raise ValueError('必要资源缺失：'+name)
    page=(source/'index.html').read_text();script=(source/'app.js').read_text();report=json.loads((source/'results.json').read_text())
    if 'A股筛选雷达' not in page or '不使用演示行情' not in page or '盘后' not in page:raise ValueError('不是盘后真实筛选页面')
    if "fetch('./results.json'" not in script or "fetch('./stocks.json'" in script:raise ValueError('数据入口错误')
    if report.get('schemaVersion')!=3 or report.get('screeningMode')!='after_close' or report.get('dataMode')!='real' or report.get('scopePolicy')!=POLICY:raise ValueError('拒绝旧版盘中或无排除策略报告')
    if not isinstance(report.get('stocks'),list) or not isinstance(report.get('errors'),list):raise ValueError('缺少结果/错误字段')
    if len(report['stocks'])!=report.get('scannedCount'):raise ValueError('扫描数量不一致')
    for row in report['stocks']:
        if exclusion_reason(row):raise ValueError('结果包含范围外股票')
        if row.get('screeningMode')!='after_close' or row.get('selectionDate')!=report.get('selectionDate'):raise ValueError('选股日期/模式不一致')
        checks=row.get('checks',[])
        if len(checks)!=5 or sorted(c.get('id','') for c in checks)!=sorted(['trend','gains','volume','earnings','funds']):raise ValueError('五项条件不完整')
        expected='unknown' if any(c.get('status')=='unknown' for c in checks) else 'selected' if all(c.get('status')=='pass' for c in checks) else 'rejected'
        if row.get('status')!=expected:raise ValueError('必要数据缺失不能入选')
        if row['status']=='selected':
            by={c['id']:c for c in checks};dates=session_dates(report['selectionDate'])[-3:]
            for key in ('gains','volume'):
                days=by[key].get('evidence',{}).get('days',[])
                if [d.get('date') for d in days]!=dates or any(d.get('status')!='pass' for d in days):raise ValueError('三日证据不完整')
            if by['funds'].get('evidence',{}).get('tradeDate')!=report['selectionDate']:raise ValueError('资金日期不符')
    output.mkdir(parents=True)
    # Do not publish the previous historical shortlist as after-close results.
    for name in required:shutil.copy2(source/name,output/name)
    shutil.copytree(output,output/'static')
    meta=json.dumps(dict(commit=commit,builtAt=datetime.now(timezone.utc).isoformat(),frontend='after-close-v3',dataMode='real'),ensure_ascii=False,indent=2)+'\n'
    (output/'build.json').write_text(meta);(output/'static/build.json').write_text(meta)
    print('Validated date-locked after-close frontend, '+commit)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--commit',required=True)
    args=p.parse_args();build(args.output,args.commit)
