import copy
import unittest
from datetime import datetime, timedelta

from radar.engine import CHINA, evaluate


def fixture():
    """Artificial data for boundary tests only, never published as scan results."""
    now = datetime(2026, 9, 30, 10, 5, tzinfo=CHINA)
    day = now.date() - timedelta(days=1)
    dates = []
    while len(dates) < 120:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day -= timedelta(days=1)
    dates.reverse()
    history = [{'date': date, 'close': 100, 'high': 101, 'low': 99, 'volume': 900, 'changePercent': 0} for date in dates]
    history[20].update(close=130, high=140, low=129)
    history[60].update(close=96, high=97, low=95)
    history[-2].update(close=102, high=103, low=101, volume=1000, changePercent=2)
    history[-1].update(close=104.04, high=105, low=103, volume=1100, changePercent=2)
    points = []
    for date, volume in [(dates[-1], 100), (now.date().isoformat(), 120)]:
        start = datetime.fromisoformat(date + 'T09:30:00').replace(tzinfo=CHINA)
        for i in range(35):
            points.append({'time': (start + timedelta(minutes=i)).isoformat(), 'volume': volume})
    bundle = {'symbol': '600000', 'name': '单元测试输入', 'calendar': dates, 'history': history, 'minutes': points,
              'quote': {'price': 106.1208, 'previousClose': 104.04, 'asOf': now.isoformat()},
              'funds': {'netInflow': 100, 'asOf': now.isoformat()},
              'financial': {'period': '2026-06-30', 'announcedAt': '2026-08-25', 'netProfit': 1000},
              'forecasts': []}
    return bundle, now


class EngineTests(unittest.TestCase):
    def check(self, bundle, now, key):
        return next(c for c in evaluate(bundle, now)['checks'] if c['id'] == key)

    def test_all_rules_required(self):
        bundle, now = fixture()
        self.assertEqual(evaluate(bundle, now)['status'], 'selected')
        self.assertTrue(all(c['status'] == 'pass' for c in evaluate(bundle, now)['checks']))

    def test_gains_boundaries(self):
        for value, expected in [(0, 'fail'), (-1, 'fail'), (3, 'pass'), (3.001, 'fail')]:
            with self.subTest(value=value):
                bundle, now = fixture()
                bundle['history'][-2]['changePercent'] = value
                self.assertEqual(self.check(bundle, now, 'gains')['status'], expected)

    def test_current_gain_exact_upper_bound(self):
        bundle, now = fixture()
        bundle['quote'].update(price=103, previousClose=100)
        self.assertEqual(self.check(bundle, now, 'gains')['status'], 'pass')
        bundle['quote']['price'] = 103.00001
        self.assertEqual(self.check(bundle, now, 'gains')['status'], 'fail')

    def test_volume_boundaries(self):
        for multiplier, expected in [(1, 'fail'), (1.5, 'pass'), (1.5001, 'fail'), (.9, 'fail')]:
            with self.subTest(multiplier=multiplier):
                bundle, now = fixture()
                for point in bundle['minutes']:
                    if point['time'].startswith(now.date().isoformat()):
                        point['volume'] = 100 * multiplier
                self.assertEqual(self.check(bundle, now, 'volume')['status'], expected)

    def test_daily_volume_each_pair(self):
        bundle, now = fixture()
        bundle['history'][-1]['volume'] = 1600
        self.assertEqual(self.check(bundle, now, 'volume')['status'], 'fail')
        bundle['history'][-1]['volume'] = 1000
        self.assertEqual(self.check(bundle, now, 'volume')['status'], 'fail')

    def test_current_partial_minute_not_counted(self):
        bundle, now = fixture()
        bundle['minutes'].append({'time': now.isoformat(), 'volume': 1000000})
        check = self.check(bundle, now, 'volume')
        self.assertEqual(check['status'], 'pass')
        self.assertEqual(check['evidence']['cutoff'], '10:04')

    def test_yesterday_same_time_not_whole_day(self):
        bundle, now = fixture()
        bundle['minutes'].append({'time': bundle['calendar'][-1] + 'T14:00:00+08:00', 'volume': 1000000})
        self.assertEqual(self.check(bundle, now, 'volume')['status'], 'pass')

    def test_missing_minute_is_unknown(self):
        bundle, now = fixture()
        bundle['minutes'].pop(12)
        self.assertEqual(self.check(bundle, now, 'volume')['status'], 'unknown')
        self.assertEqual(evaluate(bundle, now)['status'], 'unknown')

    def test_duplicate_minute_is_unknown(self):
        bundle, now = fixture()
        bundle['minutes'].append(copy.deepcopy(bundle['minutes'][3]))
        self.assertEqual(self.check(bundle, now, 'volume')['status'], 'unknown')

    def test_missing_data_dominates_failed_rule(self):
        bundle, now = fixture()
        bundle['funds']['netInflow'] = -1
        del bundle['minutes']
        self.assertEqual(evaluate(bundle, now)['status'], 'unknown')

    def test_nonpositive_funds(self):
        for value in (0, -1):
            bundle, now = fixture()
            bundle['funds']['netInflow'] = value
            self.assertEqual(evaluate(bundle, now)['status'], 'rejected')

    def test_stale_or_future_data(self):
        for delta in (-181, 1):
            bundle, now = fixture()
            bundle['quote']['asOf'] = (now + timedelta(seconds=delta)).isoformat()
            self.assertEqual(self.check(bundle, now, 'gains')['status'], 'unknown')
            self.assertEqual(evaluate(bundle, now)['status'], 'unknown')

    def test_insufficient_history_and_suspension(self):
        bundle, now = fixture()
        bundle['history'].pop(30)
        self.assertEqual(self.check(bundle, now, 'trend')['status'], 'unknown')
        bundle, now = fixture()
        bundle['history'][30]['volume'] = 0
        self.assertEqual(self.check(bundle, now, 'trend')['status'], 'unknown')

    def test_drawdown_strictly_over_twenty_percent(self):
        bundle, now = fixture()
        for row in bundle['history']:
            row.update(close=100, high=100, low=90)
        bundle['history'][20].update(high=100, low=90)
        bundle['history'][60].update(close=81, low=80)
        bundle['history'][-3].update(close=90)
        bundle['history'][-2].update(close=95)
        bundle['history'][-1].update(close=96)
        self.assertEqual(self.check(bundle, now, 'trend')['status'], 'fail')
        bundle['history'][60]['low'] = 79.99
        self.assertEqual(self.check(bundle, now, 'trend')['status'], 'pass')

    def test_peak_has_to_precede_trough(self):
        bundle, now = fixture()
        bundle['history'][-3]['high'] = 200
        self.assertEqual(self.check(bundle, now, 'trend')['status'], 'fail')

    def test_formal_turnaround_forecast(self):
        bundle, now = fixture()
        bundle['financial']['netProfit'] = -100
        bundle['forecasts'] = [{'period': '2026-09-30', 'announcedAt': '2026-09-28',
                                'type': '扭亏', 'metric': '归属于上市公司股东的净利润',
                                'official': True, 'profitLower': 100, 'previousProfit': -100}]
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'pass')
        bundle['forecasts'][0]['official'] = False
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'unknown')

    def test_forecast_revisions_and_superseded_forecast(self):
        bundle, now = fixture()
        bundle['financial']['netProfit'] = -100
        good = {'period': '2026-09-30', 'announcedAt': '2026-09-25', 'type': '扭亏', 'metric': '净利润',
                'official': True, 'profitLower': 100, 'previousProfit': -100}
        revision = {**good, 'announcedAt': '2026-09-29', 'type': '预亏', 'profitLower': -50}
        bundle['forecasts'] = [good, revision]
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'fail')
        bundle['forecasts'] = [{**good, 'period': '2026-06-30'}]
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'fail')

    def test_or_logic_with_missing_report(self):
        bundle, now = fixture()
        del bundle['financial']
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'unknown')
        bundle['forecasts'] = [{'period': '2026-09-30', 'announcedAt': '2026-09-28',
                                'type': '扭亏', 'metric': '净利润', 'official': True,
                                'profitLower': 100, 'previousProfit': -100}]
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'unknown')

    def test_after_hours_not_current_qualified(self):
        bundle, now = fixture()
        after_hours = now.replace(hour=18)
        bundle['quote']['asOf'] = after_hours.isoformat()
        bundle['funds']['asOf'] = after_hours.isoformat()
        self.assertEqual(evaluate(bundle, after_hours)['status'], 'unknown')

    def test_invalid_numbers_do_not_select(self):
        for value in (None, 'NaN', 'Infinity', '-', True):
            bundle, now = fixture()
            bundle['funds']['netInflow'] = value
            self.assertEqual(self.check(bundle, now, 'funds')['status'], 'unknown')

    def test_missing_forecast_classification_is_unknown(self):
        bundle, now = fixture()
        bundle['financial']['netProfit'] = -100
        bundle['forecasts'] = [{'period': '2026-09-30', 'announcedAt': '2026-09-28'}]
        self.assertEqual(self.check(bundle, now, 'earnings')['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
