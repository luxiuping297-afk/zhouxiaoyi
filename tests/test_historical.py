import unittest
from decimal import Decimal
from radar.historical import verified_change, analyze
from radar.fallback import tencent_history
from radar.engine import CHINA
from datetime import datetime,timedelta


def bar(date,close):
    return dict(date=date,open=close,close=close,high=close,low=close,volume='100.00',corporateAction={})

class HistoricalTests(unittest.TestCase):
    def test_safe_increase_and_decline(self):
        a=bar('2026-09-28','100.00')
        for price,state in [('102.00','pass'),('99.00','fail'),('103.10','fail')]:
            b=bar('2026-09-29',price)
            result=verified_change(a,b,a,b)
            self.assertEqual(result['status'],state)
            self.assertEqual(Decimal(result['percent']),(Decimal(price)/100-1)*100)

    def test_threshold_rounding_is_unknown(self):
        a=bar('2026-09-28','100.00')
        for price in ('103.00','100.00','100.01','103.01'):
            b=bar('2026-09-29',price)
            self.assertEqual(verified_change(a,b,a,b)['status'],'unknown')

    def test_dividend_and_future_cash_adjustment_not_misclassified(self):
        raw_a,raw_b=bar('2026-06-25','1212.10'),bar('2026-06-26','1168.63')
        q_a,q_b=bar('2026-06-25','1184.08'),bar('2026-06-26','1168.63')
        self.assertEqual(verified_change(q_a,q_b,raw_a,raw_b)['status'],'unknown')
        # Same future cash subtraction can change a normal day's ratio too.
        self.assertEqual(verified_change(bar('2026-06-23','80.00'),bar('2026-06-24','83.00'),
            bar('2026-06-23','100.00'),bar('2026-06-24','103.00'))['status'],'unknown')

    def test_unexplained_corporate_action_unknown(self):
        a,b=bar('2026-09-28','100.00'),bar('2026-09-29','102.00')
        b['corporateAction']={'event':'unverified'}
        self.assertEqual(verified_change(a,b,a,b)['status'],'unknown')

    def test_computed_fallback_and_missing_raw(self):
        rows=[[(datetime(2026,1,1)+timedelta(days=i)).date().isoformat(),'100.00','100.00','100.00','100.00','100.00',{}] for i in range(121)]
        rows[-1][1:5]=['102.00']*4
        def fetch(url,params):
            key='qfqday' if params['param'].endswith('qfq') else 'day'
            return {'data':{'sh600519':{key:rows}}}
        result=tencent_history('600519',datetime(2026,10,6,tzinfo=CHINA),fetch=fetch)
        self.assertEqual(Decimal(result[-1]['changePercent']),2)

    def test_partial_checks_never_formal_selection(self):
        dates=[(datetime(2026,1,1)+timedelta(days=i)).date().isoformat() for i in range(120)]
        rows=[bar(d,'100.00') for d in dates]
        for row in rows:row['high']='101.00';row['low']='99.00'
        rows[10].update(high='140.00');rows[50].update(low='90.00')
        rows[-2].update(open='102.00',close='102.00',high='103.00',volume='110.00')
        rows[-1].update(open='104.00',close='104.00',high='105.00',volume='121.00')
        result=analyze('600519',rows,rows,dates)
        self.assertEqual(result['status'],'unknown')
        self.assertFalse(result['formalSelection'])
        self.assertEqual(result['mainFunds']['status'],'unknown')
        self.assertEqual(result['intradayVolume']['status'],'unknown')
