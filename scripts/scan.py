"""Compatibility CLI: intraday scanning has been retired."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar.provider import DataError


def scan(*args,**kwargs):
    raise DataError('盘中扫描已停用；请使用 scripts/scan_after_close.py 执行盘后选股')


if __name__=='__main__':
    from scripts.scan_after_close import main
    raise SystemExit(main())
