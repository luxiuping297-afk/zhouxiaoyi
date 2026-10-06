"""Shared collector-side eligibility for ordinary SH/SZ main-board A shares."""
import re
import unicodedata
from collections import Counter

SCOPE = '沪深主板普通A股（排除创业板、科创板、北交所及ST/*ST）'
POLICY = 'sh-sz-mainboard-no-st-v1'
MAIN_PREFIXES = ('600', '601', '603', '605', '000', '001', '002', '003')


def exclusion_reason(record):
    symbol = record.get('symbol', '')
    if symbol.startswith('30'): return '创业板'
    if symbol.startswith(('688', '689')): return '科创板'
    if record.get('exchange') == '京' or symbol.startswith(('43', '83', '87', '88', '92')): return '北交所'
    if len(symbol) != 6 or not symbol.isdigit() or not symbol.startswith(MAIN_PREFIXES): return '非沪深主板普通A股'
    expected = '沪' if symbol.startswith('6') else '深'
    if record.get('exchange') != expected: return '证券市场身份无法确认'
    name = record.get('name')
    if not isinstance(name, str) or not name.strip(): return '缺少名称，无法排除ST/*ST'
    normalized = re.sub(r'\s+', '', unicodedata.normalize('NFKC', name)).upper()
    if re.match(r'^(?:(?:XD|XR|DR))*S?\*?ST', normalized): return 'ST/*ST'
    return None


def restrict(records):
    eligible, excluded = [], []
    for record in records:
        reason = exclusion_reason(record)
        if reason: excluded.append(dict(**record, exclusionReason=reason))
        else: eligible.append(record)
    return eligible, dict(scopePolicy=POLICY, scope=SCOPE, beforeExclusionCount=len(records),
                         eligibleUniverseCount=len(eligible), excludedCount=len(excluded),
                         exclusionCounts=dict(Counter(r['exclusionReason'] for r in excluded)),
                         excludedStocks=excluded,
                         exchangeUniverseCounts={x:sum(r['exchange']==x for r in eligible) for x in ('沪','深')})
