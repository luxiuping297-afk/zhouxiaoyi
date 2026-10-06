import unittest
from datetime import datetime
from unittest.mock import patch
from radar.scope import exclusion_reason, restrict
from radar.engine import CHINA
from scripts.scan import scan
from scripts.scan_history_market import screen


def record(symbol, name='普通股票', exchange=None):
    return dict(symbol=symbol,name=name,exchange=exchange or ('沪' if symbol.startswith('6') else '深'))


class ScopeTests(unittest.TestCase):
    def test_mainboards_include_former_sme_and_new_mainboard(self):
        for s in ('600519','601001','603001','605001','000001','001001','002001','003001'):
            self.assertIsNone(exclusion_reason(record(s)))

    def test_all_exclusions_and_unknown_identity(self):
        for r in (record('300750'),record('301001'),record('688001'),record('920149',exchange='京'),
                  record('600001','ST股票'),record('600002','*ST股票'),record('000001','ＳＴ股票'),
                  record('000001',' * st 股票'),record('002001','S*ST股票'),record('600001',''),
                  record('600001','XD*ST股票'),record('000001','DRST股票'),
                  record('600001',exchange='深'),record('900001'),record('302132')):
            self.assertIsNotNone(exclusion_reason(r))
        eligible, stats=restrict([record('600519'),record('300750'),record('600002','*ST股票')])
        self.assertEqual([r['symbol'] for r in eligible],['600519'])
        self.assertEqual((stats['beforeExclusionCount'],stats['excludedCount'],stats['eligibleUniverseCount']),(3,2,1))

    def test_historical_exclusions_prevent_any_data_request(self):
        class NoRequests:
            def bars(self,*args):raise AssertionError('Excluded security must not be fetched')
        for r in (record('300750'),record('688001'),record('920149',exchange='京'),record('600001','*ST股票')):
            self.assertEqual(screen(r,['2026-09-30'],NoRequests())['state'],'scope_excluded')

    @patch('scripts.scan.market_status',return_value={'state':'open'})
    def test_live_explicit_symbols_cannot_bypass_scope(self,_):
        records=[record('600519'),record('300750'),record('600001','*ST股票')]
        class Provider:
            name='test-only'
            requested=[]
            def calendar(self,*args):return ['2026-09-30']
            def collect(self,symbol,calendar):
                self.requested.append(symbol)
                return dict(symbol=symbol,name='普通股票',calendar=calendar)
        provider=Provider()
        r=scan(provider,['600519','300750','600001'],listing=dict(stocks=records,source='https://example.test',fetchedAt='2026-09-30'))
        self.assertEqual(provider.requested,['600519'])
        self.assertEqual([x['symbol'] for x in r['stocks']],['600519'])
        self.assertEqual(r['excludedRequestedSymbols'],['300750','600001'])

    @patch('scripts.scan.market_status',return_value={'state':'open'})
    def test_live_new_st_name_is_not_evaluated(self,_):
        class Provider:
            name='test-only'
            def calendar(self,*args):return ['2026-09-30']
            def collect(self,*args):return dict(symbol='600519',name='*ST测试')
        r=scan(Provider(),['600519'],listing=dict(stocks=[record('600519')],source='https://example.test',fetchedAt='2026-09-30'))
        self.assertEqual(r['stocks'],[])
        self.assertFalse(r['complete'])
