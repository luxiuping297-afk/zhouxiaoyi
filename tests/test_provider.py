import unittest
from datetime import datetime

from radar.engine import CHINA
from radar.provider import DataError, Eastmoney, numeric, valid_symbol
from scripts.scan import scan


class ProviderTests(unittest.TestCase):
    def test_empty_forecast_not_assumed_from_null(self):
        for payload in ({'success': False}, {'success': True, 'result': None},
                        {'success': True, 'result': {'data': [], 'count': 1}}):
            provider = Eastmoney(fetch=lambda *args: payload)
            with self.assertRaises(DataError):
                provider.reports('forecasts', '600000', datetime(2026, 9, 30, tzinfo=CHINA))

    def test_verified_empty_forecast(self):
        provider = Eastmoney(fetch=lambda *args: {'success': True, 'result': {'data': [], 'count': 0}})
        self.assertEqual(provider.reports('forecasts', '600000', datetime(2026, 9, 30, tzinfo=CHINA)), [])

    def test_missing_funds_not_zero(self):
        provider = Eastmoney(fetch=lambda *args: {'data': {'diff': [{'f12': '600000', 'f13': 1, 'f14': '测试输入', 'f2': 10, 'f18': 9, 'f124': 1790733900}]}})
        quote, funds = provider.quote('600000')
        self.assertEqual(quote['price'], 10)
        self.assertIsNone(funds)

    def test_financial_exact_fields(self):
        row = {'SECURITY_CODE': '600000', 'REPORTDATE': '2026-06-30 00:00:00',
               'UPDATE_DATE': '2026-08-25 00:00:00', 'PARENT_NETPROFIT': -42}
        provider = Eastmoney(fetch=lambda *args: {'success': True, 'result': {'data': [row], 'pages': 1}})
        result = provider.reports('financial', '600000', datetime(2026, 9, 30, tzinfo=CHINA))
        self.assertEqual(result['netProfit'], -42)

    def test_wrong_market_or_symbol_not_accepted(self):
        provider = Eastmoney(fetch=lambda *args: {'data': {'diff': [{'f12': '000001', 'f13': 1, 'f2': 3000, 'f18': 2990, 'f124': 1790733900}]}})
        with self.assertRaises(DataError):
            provider.quote('000001')
        provider = Eastmoney(fetch=lambda *args: {'data': {'code': '600000', 'market': 1,
            'trends': ['2026-09-30 09:30,10,10,10,10,1,100,10']}})
        with self.assertRaises(DataError):
            provider.minutes('600519')

    def test_universe_must_be_complete(self):
        provider = Eastmoney(fetch=lambda *args: {'data': {'total': 2, 'diff': [{'f12': '600000'}]}})
        with self.assertRaises(DataError):
            provider.universe()

    def test_network_blocker_not_empty_success(self):
        class Offline(Eastmoney):
            def collect(self, symbol, calendar):
                return {'symbol': symbol, 'calendar': calendar, 'errors': []}
            def calendar(self, now):
                raise DataError('blocked')
            def universe(self):
                raise DataError('blocked')
        report = scan(Offline())
        self.assertFalse(report['complete'])
        self.assertEqual(report['counts']['selected'], 0)
        self.assertEqual(report['dataMode'], 'real')
        self.assertTrue(report['errors'])

    def test_selected_scope_missing_calendar(self):
        class Offline(Eastmoney):
            def collect(self, symbol, calendar):
                return {'symbol': symbol, 'calendar': calendar, 'errors': []}
            def calendar(self, now):
                raise DataError('blocked')
        report = scan(Offline(), ['600000'])
        self.assertFalse(report['complete'])
        self.assertEqual(report['stocks'][0]['status'], 'unknown')
        self.assertEqual(len(report['stocks'][0]['checks']), 5)

    def test_symbol_validation(self):
        for symbol in ('600519', '000001', '300750', '920001'):
            self.assertEqual(valid_symbol(symbol), symbol)
        for symbol in ('../secrets', '1.600519', '510300', '900001', '600519&token=x'):
            with self.assertRaises(DataError):
                valid_symbol(symbol)

    def test_nonfinite_or_overflow_numeric_is_rejected(self):
        for value in ('1e9999', 'NaN', None, True):
            with self.assertRaises(DataError):
                numeric(value)

    def test_preflight_blocks_batch_before_requests(self):
        class MustNotRequest(Eastmoney):
            def calendar(self, now):
                raise DataError('sample unavailable')
            def collect(self, symbol, calendar):
                return {'symbol': symbol}
            def universe(self):
                raise AssertionError('Must not request full market')
        caps = {'checks': [{'kind': key, 'status': 'reachable', 'message': ''} for key in ('history', 'minutes', 'financial', 'forecasts')] +
                          [{'kind': 'funds', 'status': 'partial', 'message': 'daily only'}]}
        report = scan(MustNotRequest(), capabilities=caps)
        self.assertFalse(report['complete'])
        self.assertEqual(len(report['stocks']), 3)
        self.assertTrue(report['errors'])


if __name__ == '__main__':
    unittest.main()
