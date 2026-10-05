import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from radar.engine import CHINA
from radar.fallback import tencent_history, VerifiedFallback
from radar.provider import DataError


class FallbackTests(unittest.TestCase):
    def rows(self):
        start = datetime(2026, 1, 1)
        return [[(start + timedelta(days=i)).strftime('%Y-%m-%d'), '10', '10', '11', '9', '100'] for i in range(121)]

    def test_history_does_not_invent_vendor_gain(self):
        fetch = lambda *args: {'data': {'sh600519': {'qfqday': self.rows()}}}
        result = tencent_history('600519', datetime(2026, 10, 6, tzinfo=CHINA), fetch=fetch)
        self.assertEqual(len(result), 120)
        self.assertIsNone(result[-1]['changePercent'])
        self.assertEqual(result[-1]['volume'], 100)

    def test_wrong_identity_and_unverified_beijing_rejected(self):
        fetch = lambda *args: {'data': {'sz000001': {'qfqday': self.rows()}}}
        with self.assertRaises(DataError):
            tencent_history('600519', datetime.now(CHINA), fetch=fetch)
        with self.assertRaises(DataError):
            tencent_history('920001', datetime.now(CHINA), fetch=fetch)

    def test_fallback_quote_never_supplies_funds(self):
        p = VerifiedFallback(fetch=lambda *args: (_ for _ in ()).throw(DataError('HTTP 502')))
        q = dict(price=10, previousClose=9.9, name='fixture', asOf='2026-09-30T15:00:00+08:00')
        with patch('radar.fallback.tencent_history', return_value=[{'date': '2026-09-30'}]), patch('radar.fallback.tencent_quote', return_value=q):
            b = p.collect('600519', ['2026-09-30'])
        self.assertIsNone(b['funds'])
        self.assertTrue(any(e['kind'] == 'funds' for e in b['errors']))
        self.assertEqual(b['quote']['asOf'], q['asOf'])
