import unittest
from datetime import datetime
from unittest.mock import patch
from radar.provider import DataError, get_json
from http.client import IncompleteRead
from radar.universe import universe
from radar.engine import CHINA
from scripts.scan_history_market import volume_prefilter, financial_check


class MarketHistoryTests(unittest.TestCase):
    def test_truncated_network_response_becomes_unknown_not_crash(self):
        with patch('radar.provider.urlopen', side_effect=IncompleteRead(b'partial')):
            with self.assertRaises(DataError):get_json('https://example.test', {})

    def test_complete_pagination_and_market_identity(self):
        def fetch(url,p):
            offset=p['offset'];n=min(200,201-offset)
            rows=[dict(code='sh'+str(600000+offset+i),name='test-only') for i in range(n)]
            return {'code':0,'data':dict(offset=offset,total=201,rank_list=rows)}
        r=universe(fetch)
        self.assertEqual(len(r['stocks']),201)
        self.assertTrue(r['complete'])
        self.assertEqual(r['exchangeCounts']['沪'],201)

    def test_duplicates_and_wrong_offset_rejected(self):
        for payload in (
            {'code':0,'data':dict(offset=0,total=2,rank_list=[{'code':'sh600000','name':'test'}]*2)},
            {'code':0,'data':dict(offset=200,total=1,rank_list=[{'code':'sh600000','name':'test'}])},
            {'code':0,'data':dict(offset=0,total=1,rank_list=[{'code':'sz920982','name':'test'}])},
        ):
            with self.assertRaises(DataError):universe(lambda *a:payload)

    def test_volume_exact_bounds_and_missing_date(self):
        calendar=['2026-09-28','2026-09-29','2026-09-30']
        rows=[dict(date=d,volume=v) for d,v in zip(calendar,['100','150','225'])]
        self.assertTrue(volume_prefilter(rows,calendar)[0])
        rows[-1]['volume']='225.0001';self.assertFalse(volume_prefilter(rows,calendar)[0])
        rows[-1]['date']='2026-09-29'
        with self.assertRaises(ValueError):volume_prefilter(rows,calendar)

    def test_missing_financial_is_not_profitable(self):
        class Blocked:
            def reports(self,*a):raise DataError('unavailable')
        r=financial_check(Blocked(),'600000',datetime(2026,10,6,tzinfo=CHINA))
        self.assertEqual(r['status'],'unknown')
        self.assertEqual(len(r['errors']),2)

    def test_profit_report_short_circuits_forecast(self):
        class Profitable:
            def reports(self,kind,*a):
                if kind=='forecasts':raise AssertionError('profit already satisfies OR')
                return dict(period='2026-06-30',announcedAt='2026-08-25',netProfit=1)
        self.assertEqual(financial_check(Profitable(),'600000',datetime(2026,10,6,tzinfo=CHINA))['status'],'pass')
