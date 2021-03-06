#!/usr/bin/env python3

from pathlib import Path
import sys
import os

sys.path.insert(0, Path().absolute().parent.as_posix())
import finac

import unittest
import logging
import rapidtables
import random
import time

from types import SimpleNamespace

TEST_DB = '/tmp/finac-test.db'

result = SimpleNamespace()
config = SimpleNamespace(remote=False)


class Test(unittest.TestCase):

    def run(self, result=None):
        if not result.errors:
            super(Test, self).run(result)

    def test002_create_account(self):
        finac.account_create('test.test', 'eur', 'current', 'Test acc')
        finac.account_create('TEST2.TEST', 'eur', 'current', 'Test acc2')

    def test003_create_transaction(self):
        result.transaction1_id = finac.transaction_create('test.test', 100,
                                                          'test',
                                                          'Test balance import',
                                                          mark_completed=False)
        self.assertEqual(finac.account_balance('TEST.TEST'), 0)
        statement = list(finac.account_statement('TEST.TEST', '20"19-01-0;1',
                                                 pending=False))
        self.assertEqual(len(statement), 0)
        statement = list(finac.account_statement('test.test', '201\'9-0"1-01',
                                                 pending=True))
        self.assertEqual(len(statement), 1)

    def test004_transaction_complete(self):
        finac.transaction_complete(result.transaction1_id)
        self.assertEqual(finac.account_balance('test.test'), 100)
        statement = list(
            finac.account_statement('test.test', '2019-01-01', pending=True))

    def test005_transaction_move(self):
        result.transaction2_id = finac.transaction_move('TEST2.TEST',
                                                        'TEST.TEST', 25,
                                                        'test', 'Test move')
        self.assertEqual(finac.account_balance('TEST.TEST'), 75)
        self.assertEqual(finac.account_balance('TEST2.TEST'), 25)

    def test006_statement_tests(self):
        statement = list(finac.account_statement('test.test', '2019-01-01'))
        self.assertEqual(len(statement), 2)
        statement = list(finac.account_statement('TEST2.TEST'))
        self.assertEqual(len(statement), 1)
        statement = list(finac.account_statement('TEST.TEST', '2119-01-01'))
        self.assertEqual(len(statement), 0)
        statement = list(
            finac.account_statement('TEST.TEST', '2019-01-01', '2119-05-22'))
        self.assertEqual(len(statement), 2)
        statement = list(
            finac.account_statement('TEST.TEST', end='2119-0"5-22'))
        self.assertEqual(len(statement), 2)
        ss = finac.account_statement_summary('TEST.TEST', end='2119-05-22')
        self.assertEqual(ss['credit'], 25)
        self.assertEqual(ss['debit'], 100)
        self.assertEqual(ss['net'], 75)

    def test007_list_summary_and_passive(self):
        finac.config.base_asset = 'eur'
        self.assertEqual(finac.account_list_summary()['total'], 100)
        finac.account_create('supplier1', 'eur', tp='supplier')
        finac.account_create('taxes1', 'eur', tp='tax')
        finac.tr('supplier1', 10)
        finac.tr('taxes1', 10)
        self.assertEqual(finac.account_list_summary()['total'], 80)
        finac.ls(group_by='asset')

    def test020_transaction_delete(self):
        finac.transaction_delete(result.transaction2_id)
        self.assertEqual(finac.account_balance('TEST.TEST'), 100)
        self.assertEqual(finac.account_balance('TEST2.TEST'), 0)

    def test021_transaction_purge(self):
        self.assertEqual(finac.purge()['transaction'], 1)

    def test030_delete_account_and_movements(self):
        finac.transaction_move('TEST2.TEST', 'TEST.TEST', 60, 'test',
                               'Test move')
        finac.account_delete('TEST.TEST')
        self.assertEqual(finac.account_balance('TEST2.TEST'), 60)

    def test040_overdraft(self):

        # allow overdraft
        finac.account_create('TEST3.TEST', 'eur', 'current', 'Test account',
                             max_overdraft=900)
        finac.transaction_create('TEST3.TEST', 100)
        finac.transaction_move('TEST2.TEST', 'TEST3.TEST', '1,000.00')
        self.assertEqual(finac.account_balance('TEST3.TEST'), -900)

        # forbid overdraft
        finac.account_create('TEST4.TEST', 'eur', 'current', 'Test account',
                             max_overdraft=200)
        finac.transaction_create('TEST3.TEST', 1200)
        try:
            finac.transaction_move('TEST2.TEST', 'TEST3.TEST', 2000)
            raise RuntimeError('OverdraftError not raised')
        except finac.OverdraftError:
            self.assertEqual(finac.account_balance('TEST3.TEST'), 300)

    def test041_max_balance(self):
        finac.account_create('TEST5.TEST', 'EUR', max_balance=100)
        finac.account_create('TEST6.TEST', 'EUR', max_balance=100)
        finac.transaction_create('TEST5.TEST', 10)
        try:
            finac.transaction_create('TEST5.TEST', 101)
            raise RuntimeError('OverlimitError not raised')
        except finac.OverlimitError:
            self.assertEqual(finac.account_balance('TEST5.TEST'), 10)
        finac.transaction_create('TEST6.TEST', 100)
        try:
            finac.transaction_move('TEST6.TEST', 'TEST5.TEST', 10)
            raise RuntimeError('OverlimitError not raised')
        except finac.OverlimitError:
            self.assertEqual(finac.account_balance('TEST5.TEST'), 10)
            self.assertEqual(finac.account_balance('TEST6.TEST'), 100)

    def test042_overdraft_and_delete(self):
        finac.account_create('TEST42.TEST', 'EUR', max_overdraft=100)
        finac.transaction_create('TEST42.TEST', 10)
        tid = finac.transaction_create('TEST42.TEST', -100,
                                       mark_completed=False)
        finac.transaction_delete(tid)
        tid = finac.transaction_create('TEST42.TEST', -100,
                                       mark_completed=False)
        finac.transaction_delete(tid)
        self.assertEqual(finac.account_balance('TEST42.TEST'), 10)

    def test050_hack_overdraft(self):
        finac.account_create('TEST.HO', 'EUR', max_overdraft=100)
        tid = finac.transaction_create('TEST.HO', -100, mark_completed=False)
        self.assertEqual(finac.account_balance('TEST.HO'), -100)
        try:
            finac.transaction_create('TEST.HO', -10, mark_completed=False)
            raise RuntimeError('Overdraft hacked')
        except finac.OverdraftError:
            pass
        finac.transaction_complete(tid)
        self.assertEqual(finac.account_balance('TEST.HO'), -100)

    def test051_hack_overlimit(self):
        finac.account_create('TEST.HL', 'EUR', max_balance=100)
        t1 = finac.transaction_create('TEST.HL', 100, mark_completed=False)
        try:
            t2 = finac.transaction_create('TEST.HL', 100, mark_completed=False)
            finac.transaction_complete(t1)
            finac.transaction_complete(t2)
            raise RuntimeError('Overlimit hacked')
        except finac.OverlimitError:
            return

    def test060_asset_rate_set(self):
        finac.asset_create('AUD')
        finac.asset_set_rate('EUR', 'USD', 1.5, date='2019-01-01')
        finac.asset_set_rate('EUR/USD', value=2)
        finac.asset_set_rate('AUD/USD', value=0.69)
        try:
            finac.asset_rate('EUR', 'USD', date='2018-01-01')
            raise RuntimeError('Rate not found not raised')
        except finac.RateNotFound:
            pass
        self.assertEqual(finac.asset_rate('EUR', 'USD', date='2019-01-05'),
                         1.5)
        self.assertEqual(finac.asset_rate('EUR', 'USD'), 2)

    def test061_asset_rate_easyget(self):
        finac.config.rate_allow_reverse = False
        try:
            finac.asset_rate('USD', 'EUR', date='2019-01-05')
            raise RuntimeError('Rate not found not raised')
        except:
            pass
        finac.config.rate_allow_reverse = True
        self.assertEqual(finac.asset_rate('USD', 'EUR', date='2019-01-05'),
                         1 / 1.5)
        self.assertEqual(finac.asset_rate('USD', 'EUR'), 1 / 2)

    def test062_asset_rate_delete(self):
        finac.asset_set_rate('EUR', 'USD', value=1.8, date='2018-12-01')
        self.assertEqual(finac.asset_rate('EUR', 'USD', date='2019-01-05'),
                         1.5)
        finac.asset_delete_rate('EUR', 'USD', date='2019-01-01')
        self.assertEqual(finac.asset_rate('EUR', 'USD', date='2019-01-05'),
                         1.8)

    def test070_test_targets_and_tags(self):
        finac.account_create('TT1', 'EUR', tp='credit')
        finac.account_create('TT2', 'EUR', tp='saving')
        finac.transaction_create('TT1', 1000)
        finac.transaction_create('TT2', 1000)
        self.assertEqual(finac.account_balance('TT1'), 1000)
        self.assertEqual(finac.account_balance('TT2'), 1000)
        finac.transaction_create('TT1', target=1500)
        finac.transaction_create('TT2', target=800)
        self.assertEqual(finac.account_balance('TT1'), 1500)
        self.assertEqual(finac.account_balance('TT2'), 800)
        finac.transaction_move('TT1', 'TT2', target_ct=700, tag='loans')
        self.assertEqual(finac.account_balance('TT1'), 1600)
        self.assertEqual(finac.account_balance('TT2'), 700)
        finac.transaction_move('TT2', 'TT1', target_dt=2000, tag='loans')
        self.assertEqual(finac.account_balance('TT1'), 300)
        self.assertEqual(finac.account_balance('TT2'), 2000)
        self.assertEqual(
            len(list(finac.account_statement('TT1', tag='lo;an"s'))), 2)
        print()
        finac.ls('TT2')
        print()

    def test071_test_list(self):
        for c in list(finac.account_list()):
            if c['account'] == 'TT1':
                self.assertEqual(c['balance'], 300)
            elif c['account'] == 'TT2':
                self.assertEqual(c['balance'], 2000)
        print()
        finac.ls()
        print()

    def test072_account_update(self):
        finac.account_update('TT2', code='TEST_ACC_2', note='Test acc #2')
        finac.account_update('TEST_ACC_2', max_overdraft=1000)
        self.assertEqual(finac.account_info('TEST_ACC_2')['max_overdraft'],
            1000)

    def test080_lazy_exchange(self):
        finac.account_create('eur1', 'eur')
        finac.account_create('usd1', 'usd')
        if not config.remote:
            finac.config.lazy_exchange = False
            try:
                finac.transaction_move('usd1', 'eur1', 20)
                raise RuntimeError(
                    'Lazy exchange is off but asset mismatch not detected')
            except ValueError:
                pass
            finac.config.lazy_exchange = True
        time.sleep(1)
        finac.asset_set_rate('EUR/USD', value=1.1)

        finac.transaction_move('usd1', 'eur1', 20, xdt=False)
        self.assertEqual(finac.account_balance('eur1'), -20)
        self.assertEqual(finac.account_balance('usd1'), 22)

        finac.transaction_move('usd1', 'eur1', 20)
        self.assertEqual(finac.account_balance('eur1'), -38.18)
        self.assertEqual(finac.account_balance('usd1'), 42)

        t1, t2 = finac.transaction_move('usd1', 'eur1', 20, rate=1.25)
        self.assertEqual(finac.account_balance('eur1'), -54.18)
        self.assertEqual(finac.account_balance('usd1'), 62)

        finac.transaction_delete(t1)
        self.assertEqual(finac.account_balance('eur1'), -38.18)
        self.assertEqual(finac.account_balance('usd1'), 42)

        t1, t2 = finac.transaction_move('usd1', 'eur1', 20, rate=1.25)
        self.assertEqual(finac.account_balance('eur1'), -54.18)
        self.assertEqual(finac.account_balance('usd1'), 62)

        finac.transaction_delete(t2)
        self.assertEqual(finac.account_balance('eur1'), -38.18)
        self.assertEqual(finac.account_balance('usd1'), 42)

    def test081_test_cross(self):
        finac.asset_create('NZD')
        finac.asset_create('BZD')
        finac.asset_create('FKP')
        finac.asset_create('KPW')
        finac.asset_set_rate('NZD/BZD', value=2)
        finac.asset_set_rate('BZD/FKP', value=2.5)
        finac.asset_set_rate('FKP/KPW', value=3)
        self.assertEqual(finac.asset_rate('NZD/KPW'), 15)
        self.assertEqual(round(finac.asset_rate('KPW/NZD') * 100, 2), 6.67)

    def test082_list_recent_rates(self):
        finac.lsa('*')

    def test085_apply(self):
        finac.account_create('xtest1', 'eur')
        finac.account_create('xtest2', 'eur')
        finac.transaction_apply('transactions.yml')
        self.assertEqual(finac.account_balance('xtest1'), 300)
        self.assertEqual(finac.account_balance('xtest2'), 200)

    def test096_asset_precision(self):
        self.assertEqual(finac.asset_precision('eur'), 2)
        precs = list(finac.core._asset_precision())
        self.assertEqual(precs[0]['asset'], 'AUD')
        self.assertEqual(precs[0]['precision'], 2)
        finac.preload()

    def test097_balance_range(self):
        finac.account_create('tr', 'eur', tp='cash')
        finac.transaction_create('tr', 1000, date='2019-01-05')
        finac.transaction_create('tr', 2000, date='2019-02-05')
        finac.transaction_create('tr', -500, date='2019-04-05')
        finac.transaction_create('tr', -200, date='2019-06-05')
        finac.transaction_create('tr', 800, date='2019-08-05')
        self.assertRaises(ValueError, finac.account_balance_range,
                          account='tr', tp='cash', start='2019-01-05',
                          end='2019-8-07', base='usd')
        t, dt = finac.account_balance_range(start='2019-01-05', account='tr',
                                            end='2019-8-07',
                                            return_timestamp=False)
        self.assertEqual(dt[-3], 2300)
        self.assertEqual(dt[-1], 3100)
        t1, dt1 = finac.account_balance_range(start='2019-01-05', tp='cash',
                                              end='2019-8-07', base='usd',
                                              return_timestamp=False)
        self.assertEqual(dt1[-3], 4140)
        self.assertEqual(dt1[-1], 5580)

    def test098_asset_update(self):
        finac.asset_update('eur', code='euRo')
        self.assertEqual(finac.asset_rate('EURo/USD'), 1.1)
        finac.asset_update('euro', code='eur')

    def test099_transact_update(self):
        finac.transaction_update(41, tag='loans2', note='somenote')
        for t in finac.account_statement('TT1'):
            if t['id'] == 41:
                self.assertEqual(t['tag'], 'loans2')
                self.assertEqual(t['note'], 'somenote')

    def test100_delete_asset(self):
        finac.asset_delete('kpw')

    def test103_trans_move(self):
        finac.asset_create('UAH')
        finac.asset_set_rate('UAH/USD', value=0.04)
        finac.account_create('move.test', 'usd', 'current', 'Test move acc')
        finac.account_create('move1.TEST', 'UAH', 'current', 'Test move acc2')
        finac.transaction_create('move.test', 100, 'for move test')
        self.assertEqual(finac.account_balance('move.test'), 100)
        target_ct = 80
        target_dt = 1200
        finac.transaction_move('move1.TEST', 'move.test', target_ct=target_ct,
                               tag='go ahead', note='cross currency: target_ct')
        self.assertEqual(finac.account_balance('move.test'), target_ct)
        finac.transaction_move('move1.TEST', 'move.test', target_dt=target_dt,
                               tag='ahead', note='cross currency: target_dt')
        self.assertEqual(finac.account_balance('move1.test'), target_dt)
        self.assertRaises(ValueError, finac.transaction_move, 'move1.TEST',
                          'move.test', target_dt=100)
        print()
        finac.ls('move.test')
        finac.ls('move1.test')
        print()

    def test104_check_currency_exist(self):
        try:
            finac.asset_create('burg')
        except finac.core.ResourceNotFound:
            pass

    def test200_account_balance(self):
        self.assertRaises(ValueError, finac.account_balance, account='USD1',
                          tp='current')
        finac.account_balance(tp='current', base='usd')
        finac.account_balance(account=None, base='usd')

    def test300_parse_number(self):
        parse = finac.core.parse_number
        self.assertEqual(parse('1,000.00'), 1000)
        self.assertEqual(parse('1.000,00'), 1000)
        self.assertEqual(parse('1 000,00'), 1000)
        self.assertEqual(parse('1 000.00'), 1000)
        self.assertEqual(parse('1.000.000,00'), 1000000)
        self.assertEqual(parse('1 000 000.00'), 1000000)
        self.assertEqual(parse('1 000 000,00'), 1000000)
        self.assertEqual(parse('1,000,000.00'), 1000000)

    def test400_list_complete_delete(self):
        t1 = finac.transaction_create('move.test', 1, mark_completed=False)
        t2 = finac.transaction_create('move1.test', 1, mark_completed=False)
        finac.transaction_complete((t1, t2))
        finac.transaction_delete([t1, t2])

    def test401_account_statement_list_tag(self):
        d = finac.account_statement('MOVE.TEST', tag=['go ahead', 'ahead'])
        self.assertEqual(len(list(d)), 2)

    def test402_transaction_copy(self):
        finac.account_create('test.usd', 'usd')
        finac.account_create('test.eur', 'eur')
        finac.asset_set_rate('eur/usd', value=1.1)
        t = finac.transaction_create('test.usd', 100, tag='test', note='for move test')
        t1 = finac.transaction_move(dt='move.test', ct='test.usd', tag='copy 1', amount=10)
        t_cros = finac.transaction_move(dt='test.eur', ct='test.usd', amount=10)
        self.assertRaises(ValueError, finac.tc, transaction_ids=t_cros[1], amount=100)
        finac.tc(transaction_ids=t1, date='2019-11-15', amount=30)
        finac.tc(transaction_ids=[t, t_cros[1]])

    # passive block
    def set_balance(self, account, balance):
        finac.tr(account, target=balance)
        self.assertEqual(finac.account_balance(account), balance)

    def test700_passive_prepare(self):
        sys.stdout.write('\n\n-----Starting passive block------\n\n')
        for a in finac.asset_list():
            finac.asset_delete(a['asset'])
        finac.asset_create('usd')
        finac.asset_create('eur')
        finac.asset_set_rate('eur/usd', value=1.1)
        finac.account_create('active1', 'usd')
        finac.account_create('active2', 'eur')
        finac.account_create('passive1', 'usd', tp='finagent')
        finac.account_create('passive3', 'usd', tp='finagent')
        finac.account_create('passive2', 'eur', tp='finagent')

    def test701_passive_tr_debit(self):
        finac.tr('passive1', 100)
        self.assertEqual(finac.account_balance('passive1'), 100)

    def test702_passive_tr_credit(self):
        finac.tr('passive1', -80)
        self.assertEqual(finac.account_balance('passive1'), 20)

    def test703_passive_mv_from_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='passive1', ct='active1', amount=10)
        self.assertEqual(finac.account_balance('passive1'), 0)
        self.assertEqual(finac.account_balance('active1'), 90)

    def test704_passive_mv_to_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='active1', ct='passive1', amount=10)
        self.assertEqual(finac.account_balance('passive1'), 20)
        self.assertEqual(finac.account_balance('active1'), 110)

    def test705_target_ct_from_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='passive1', ct='active1', target_ct=90)
        self.assertEqual(finac.account_balance('passive1'), 0)
        self.assertEqual(finac.account_balance('active1'), 90)

    def test705_target_dt_from_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='passive1', ct='active1', target_dt=0)
        self.assertEqual(finac.account_balance('passive1'), 0)
        self.assertEqual(finac.account_balance('active1'), 90)

    def test706_target_ct_to_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='active1', ct='passive1', target_ct=20)
        self.assertEqual(finac.account_balance('passive1'), 20)
        self.assertEqual(finac.account_balance('active1'), 110)

    def test706_target_dt_to_active(self):
        self.set_balance('active1', 100)
        self.set_balance('passive1', 10)
        finac.mv(dt='active1', ct='passive1', target_dt=110)
        self.assertEqual(finac.account_balance('passive1'), 20)
        self.assertEqual(finac.account_balance('active1'), 110)

    def test710_passive_mv_from_active_crosscur(self):
        self.set_balance('active1', 100)
        self.set_balance('passive2', 10)
        finac.mv(dt='passive2', ct='active1', amount=5.5, xdt=False)
        self.assertEqual(finac.account_balance('passive2'), 5)
        self.assertEqual(finac.account_balance('active1'), 94.5)
        finac.mv(dt='passive2', ct='active1', amount=5, xdt=True)
        self.assertEqual(finac.account_balance('passive2'), 0)
        self.assertEqual(finac.account_balance('active1'), 89)

    def test711_passive_mv_to_active_crosscur(self):
        self.set_balance('active1', 100)
        self.set_balance('passive2', 10)
        finac.mv(dt='active1', ct='passive2', amount=5, xdt=False)
        self.assertEqual(finac.account_balance('passive2'), 15)
        self.assertEqual(finac.account_balance('active1'), 105.5)
        finac.mv(dt='active1', ct='passive2', amount=5.5, xdt=True)
        self.assertEqual(finac.account_balance('passive2'), 20)
        self.assertEqual(finac.account_balance('active1'), 111)

    def test720_mv_between_passive(self):
        self.set_balance('passive1', 100)
        self.set_balance('passive3', 100)
        finac.mv(dt='passive3', ct='passive1', amount=30)
        self.assertEqual(finac.account_balance('passive1'), 70)
        self.assertEqual(finac.account_balance('passive3'), 130)

    def test721_mv_target_dt_between_passive(self):
        self.set_balance('passive1', 100)
        self.set_balance('passive3', 100)
        finac.mv(dt='passive3', ct='passive1', target_dt=140)
        self.assertEqual(finac.account_balance('passive3'), 140)
        self.assertEqual(finac.account_balance('passive1'), 60)

    def test722_mv_target_ct_between_passive(self):
        self.set_balance('passive1', 100)
        self.set_balance('passive3', 100)
        finac.mv(dt='passive3', ct='passive1', target_ct=80)
        self.assertEqual(finac.account_balance('passive3'), 120)
        self.assertEqual(finac.account_balance('passive1'), 80)

    def test730_mv_btw_passive_crosscur(self):
        finac.account_create('pass.supplier', 'eur', tp='supplier')
        finac.account_create('pass.finagent', 'usd', tp='finagent')
        self.set_balance('pass.supplier', 100)
        self.set_balance('pass.finagent', 500)
        finac.mv(dt='pass.finagent', ct='pass.supplier', amount=10, xdt=False)
        self.assertEqual(finac.account_balance('pass.supplier'), 90)
        self.assertEqual(finac.account_balance('pass.finagent'), 511)

    def test731_mv_btw_passive_target_dt_crosscur(self):
        finac.mv(dt='pass.finagent', ct='pass.supplier', target_dt=522)
        self.assertEqual(finac.account_balance('pass.supplier'), 80)
        self.assertEqual(finac.account_balance('pass.finagent'), 522)

    def test732_mv_btw_passive_target_ct_crosscur(self):
        finac.mv(dt='pass.finagent', ct='pass.supplier', target_ct=60)
        self.assertEqual(finac.account_balance('pass.supplier'), 60)
        self.assertEqual(finac.account_balance('pass.finagent'), 544)

    def test752_passive_mv_taget_ct_from_active(self):
        finac.account_create('active.supplier', 'usd')
        self.set_balance('active.supplier', 50)
        finac.mv(dt='pass.supplier', ct='active.supplier', target_ct=40)
        self.assertEqual(finac.account_balance('pass.supplier'), 50.91)
        self.assertEqual(finac.account_balance('active.supplier'), 40)

    def test753_passive_mv_taget_dt_from_active(self):
        finac.mv(dt='pass.supplier', ct='active.supplier', target_dt=40)
        self.assertEqual(finac.account_balance('pass.supplier'), 40)
        self.assertEqual(finac.account_balance('active.supplier'), 28)

    def test754_passive_mv_taget_dt_to_active(self):
        finac.mv(dt='active.supplier', ct='pass.supplier', target_dt=40)
        self.assertEqual(finac.account_balance('pass.supplier'), 50.91)
        self.assertEqual(finac.account_balance('active.supplier'), 40)

    def test755_passive_mv_taget_ct_to_active(self):
        finac.mv(dt='active.supplier', ct='pass.supplier', target_ct=70)
        self.assertEqual(finac.account_balance('pass.supplier'), 70)
        self.assertEqual(finac.account_balance('active.supplier'), 61)

    def test755_passive_mv_targets_from_active_minus(self):
        finac.account_create('active.sup', 'usd')
        finac.account_create('pass.sup', 'eur', tp='tax')
        self.set_balance('active.sup', -50)
        self.set_balance('pass.sup', 0)
        finac.mv(dt='pass.sup', ct='active.sup', target_ct=-60)
        self.assertEqual(finac.account_balance('pass.sup'), -9.09)
        self.assertEqual(finac.account_balance('active.sup'), -60)
        finac.mv(dt='pass.sup', ct='active.sup', target_dt=-20)
        self.assertEqual(finac.account_balance('pass.sup'), -20)
        self.assertEqual(finac.account_balance('active.sup'), -72)

    def test756_passive_mv_targets_to_active_minus(self):
        finac.mv(dt='active.sup', ct='pass.sup', target_dt=-52)
        self.assertEqual(finac.account_balance('pass.sup'), -1.82)
        self.assertEqual(finac.account_balance('active.sup'), -52)
        finac.mv(dt='active.sup', ct='pass.sup', target_ct=-1)
        self.assertEqual(finac.account_balance('pass.sup'), -1)
        self.assertEqual(finac.account_balance('active.sup'), -51.10)


if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument('--debug', help='Debug mode', action='store_true')
    ap.add_argument('--remote', help='Test remote API', action='store_true')
    a = ap.parse_args()
    try:
        if a.debug:
            logging.basicConfig(level=logging.DEBUG)
            logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)
    except:
        pass
    config.remote = a.remote
    if a.remote:
        finac.init(api_uri='http://localhost:5000/jrpc', api_key='secret')
    else:
        try:
            os.unlink(TEST_DB)
        except:
            pass
        finac.init(db=TEST_DB, keep_integrity=True)
        finac.core.rate_cache = None
    test_suite = unittest.TestLoader().loadTestsFromTestCase(Test)
    test_result = unittest.TextTestRunner().run(test_suite)
    if not a.remote:
        os.unlink(TEST_DB)
    sys.exit(not test_result.wasSuccessful())
