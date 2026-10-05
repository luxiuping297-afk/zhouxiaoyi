import unittest
from datetime import datetime
from radar.engine import CHINA, Missing, fresh
from radar.market import market_status
from scripts.scan import scan

class MarketTests(unittest.TestCase):
    def test_national_day_quote_date_is_normal(self):
        s=market_status(datetime(2026,10,6,10,30,tzinfo=CHINA))
        self.assertEqual(s['state'],'closed')
        self.assertEqual(s['message'],'休市，等待下一交易日')
        self.assertEqual(s['lastTradingDate'],'2026-09-30')
        self.assertEqual(s['nextTradingDate'],'2026-10-08')

    def test_reopen_and_working_saturday(self):
        self.assertEqual(market_status(datetime(2026,10,8,10,tzinfo=CHINA))['state'],'open')
        self.assertEqual(market_status(datetime(2026,10,10,10,tzinfo=CHINA))['state'],'closed')

    def test_holiday_never_accepts_fresh_quote(self):
        now=datetime(2026,10,6,10,tzinfo=CHINA)
        with self.assertRaisesRegex(Missing,'休市'):
            fresh(now.isoformat(),now)

    def test_unknown_year_not_assumed_open(self):
        self.assertEqual(market_status(datetime(2027,10,6,10,tzinfo=CHINA))['state'],'unknown')

    def test_closed_scan_never_requests_provider(self):
        from unittest.mock import patch
        class NoRequests:
            name='test'
            def calendar(self,now):raise AssertionError('Must not request data while closed')
        with patch('scripts.scan.market_status',return_value={'state':'closed','message':'休市，等待下一交易日'}):
            r=scan(NoRequests())
        self.assertEqual(r['errors'],[])
        self.assertEqual(r['stocks'],[])
        self.assertFalse(r['liveChainVerified'])
