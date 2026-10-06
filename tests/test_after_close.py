import unittest
from copy import deepcopy
from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch
from radar.engine import CHINA,Missing
from radar.after_close import selection_date,session_dates,history_checks,funds_check,result
from scripts.scan_after_close import run


def histories():
    calendar=session_dates('2026-09-30')
    rows=[dict(date=d,open='170.000',close='170.000',high='190.000',low='170.000',volume='100',corporateAction=None) for d in calendar]
    rows[0].update(open='199.000',close='199.000',high='200.000',low='199.000')
    rows[1].update(low='160.000')
    for row,price,vol in zip(rows[-4:],(190,191,192,193),('100','110','121','133.1')):
        row.update(open=f'{price:.3f}',close=f'{price:.3f}',high=f'{price+1:.3f}',low=f'{price-1:.3f}',volume=vol)
    return deepcopy(rows),deepcopy(rows),calendar


class AfterCloseTests(unittest.TestCase):
    def test_completed_day_included_and_intraday_rejected(self):
        day=datetime(2026,9,30,20,30,tzinfo=CHINA)
        self.assertEqual(selection_date(day),'2026-09-30')
        for hour in (10,15,18):
            with self.assertRaises(Missing):selection_date(day.replace(hour=hour,minute=0))
        with self.assertRaises(Missing):selection_date(datetime(2026,10,6,20,30,tzinfo=CHINA))
        with self.assertRaises(Missing):selection_date(day,'2026-10-08')

    def test_three_gains_three_volumes_and_exact_twenty_percent(self):
        q,u,c=histories();checks=history_checks(q,u,c,'2026-09-30')
        self.assertTrue(all(v['status']=='pass' for v in checks.values()))
        self.assertEqual(checks['trend']['evidence']['drawdownPercent'],'20.0')
        self.assertEqual(len(checks['gains']['evidence']['days']),3)
        self.assertEqual([r['date'] for r in checks['volume']['evidence']['days']],c[-3:])
        self.assertEqual(checks['gains']['evidence']['days'][0]['previousDate'],c[-4])

    def test_first_gain_not_replaced_by_last_two(self):
        q,u,c=histories()
        for rows in (q,u):rows[-4].update(open='195.000',close='195.000',high='196.000',low='194.000')
        self.assertEqual(history_checks(q,u,c,'2026-09-30')['gains']['status'],'fail')

    def test_third_day_volume_exact_fifty_and_over(self):
        q,u,c=histories()
        for rows in (q,u):rows[-1]['volume']='181.5'
        self.assertEqual(history_checks(q,u,c,'2026-09-30')['volume']['status'],'pass')
        for rows in (q,u):rows[-1]['volume']='181.50001'
        self.assertEqual(history_checks(q,u,c,'2026-09-30')['volume']['status'],'fail')

    def test_stale_or_missing_daily_rows_never_substituted(self):
        q,u,c=histories()
        with self.assertRaises(Missing):history_checks(q[:-1],u,c,'2026-09-30')
        with self.assertRaises(Missing):history_checks(q,u[:10]+u[11:],c,'2026-09-30')
        with self.assertRaises(Missing):history_checks(q,u,c[:-1]+['2026-10-01'],'2026-09-30')

    def test_ex_rights_ambiguity_unknown(self):
        q,u,c=histories();q[-2]['close']='191.500'
        self.assertEqual(history_checks(q,u,c,'2026-09-30')['gains']['status'],'unknown')

    def test_funds_same_day_zero_and_negative(self):
        self.assertEqual(funds_check(dict(tradeDate='2026-09-30',netInflow=1),'2026-09-30')['status'],'pass')
        for v in (0,-1):self.assertEqual(funds_check(dict(tradeDate='2026-09-30',netInflow=v),'2026-09-30')['status'],'fail')
        with self.assertRaises(Missing):funds_check(dict(tradeDate='2026-09-29',netInflow=100),'2026-09-30')
        with self.assertRaises(Missing):funds_check(dict(tradeDate='2026-09-30',netInflow=None),'2026-09-30')

    def test_missing_data_unknown_even_if_another_condition_fails(self):
        record=dict(symbol='600519',code='sh600519',name='正常股',exchange='沪')
        row=result(record,'2026-09-30',dict(gains=dict(status='fail',reason='negative',evidence={})),datetime(2026,10,6,tzinfo=CHINA))
        self.assertEqual(row['status'],'unknown')

    def test_daily_completed_marker_prevents_second_scan(self):
        import json
        with TemporaryDirectory() as folder:
            output=Path(folder)/'results.json';original=dict(schemaVersion=3,screeningMode='after_close',scopePolicy='sh-sz-mainboard-no-st-v1',selectionDate='2026-09-30',coverageComplete=True,complete=True,running=False)
            output.write_text(json.dumps(original))
            with patch('scripts.scan_after_close.datetime') as clock,patch('scripts.scan_after_close.Reader') as reader:
                clock.now.return_value=datetime(2026,9,30,20,30,tzinfo=CHINA)
                self.assertEqual(run(output=output),0);reader.assert_not_called()
            self.assertEqual(json.loads(output.read_text()),original)
