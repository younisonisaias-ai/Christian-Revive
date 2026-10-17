"""Plain-Python checks of the expense rules and the app entry point.

Run without Odoo:  python -I church_finance/tests/test_expense_rules.py
(Odoo's own test runner uses test_expense_flow.py instead.)"""
import importlib.util
import sys
import types
import unittest
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

MODELS = Path(__file__).resolve().parents[1] / 'models'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rules = _load('_cf_test.expense_rules', MODELS / 'expense_rules.py')


class Denied(Exception):
    pass


class Invalid(ValueError):
    pass


class Duplicate(Exception):
    pass


def _load_models():
    fake = types.ModuleType('odoo')
    fake.api = types.SimpleNamespace(model=lambda fn: fn, model_create_multi=lambda fn: fn,
                                     depends=lambda *a: lambda fn: fn, constrains=lambda *a: lambda fn: fn)
    fake.models = types.SimpleNamespace(Model=object, Constraint=lambda *a: None)
    fake.fields = MagicMock()
    errors = types.ModuleType('odoo.exceptions')
    errors.AccessError, errors.UserError, errors.ValidationError = Denied, Invalid, Invalid
    psycopg = types.ModuleType('psycopg2')
    psycopg.IntegrityError = Duplicate
    pkg = types.ModuleType('_cf_test')
    pkg.__path__ = [str(MODELS)]
    with patch.dict(sys.modules, {'odoo': fake, 'odoo.exceptions': errors, 'psycopg2': psycopg,
                                  '_cf_test': pkg, '_cf_test.expense_rules': rules}):
        return _load('_cf_test.church_expense', MODELS / 'church_expense.py')


expense_models = _load_models()


def expense(state='submitted', by=5, pkr=1000):
    return {'state': state, 'submitted_by': by, 'amount_pkr': pkr}


class RuleTests(unittest.TestCase):
    def test_amounts_reject_bad_values_and_round(self):
        for raw in ('NaN', 'Infinity', '-5', '0', '0.004', True, 'abc', None, '1e15'):
            with self.assertRaises(ValueError, msg=raw):
                rules.money(raw)
        self.assertEqual(rules.money('1,250.555'), Decimal('1250.56'))
        self.assertEqual(rules.money(0, zero=True), Decimal('0.00'))

    def test_foreign_currency_needs_actual_pkr_paid(self):
        self.assertEqual(rules.pkr_amount('500', 'PKR'), Decimal('500.00'))
        with self.assertRaises(ValueError):
            rules.pkr_amount('100', 'USD')
        self.assertEqual(rules.pkr_amount('100', 'USD', '28000'), Decimal('28000.00'))
        with self.assertRaises(ValueError):
            rules.pkr_amount('100', 'XYZ', '1')

    def test_only_drafts_and_sent_back_expenses_change(self):
        self.assertTrue(rules.can_edit('pastor', 5, expense('draft')))
        self.assertTrue(rules.can_edit('pastor', 5, expense('rejected')))
        self.assertFalse(rules.can_edit('pastor', 6, expense('draft')))
        self.assertTrue(rules.can_edit('finance_officer', 6, expense('draft')))
        for state in ('submitted', 'approved', 'paid', 'reversed'):
            self.assertFalse(rules.can_edit('admin', 5, expense(state)), state)

    def test_approval_rules(self):
        limit = Decimal('50000')
        self.assertIsNone(rules.approval_problem('finance_officer', 9, expense(pkr=50000), limit))
        self.assertIn('above', rules.approval_problem('finance_officer', 9, expense(pkr=50000.01), limit))
        self.assertIsNone(rules.approval_problem('admin', 9, expense(pkr=900000), limit))
        self.assertIn('own', rules.approval_problem('admin', 5, expense(by=5), limit))
        self.assertIn('Finance or an Admin', rules.approval_problem('pastor', 9, expense(), limit))
        self.assertIn('submitted', rules.approval_problem('admin', 9, expense('draft'), limit))

    def test_pay_and_reverse_rules(self):
        self.assertIsNone(rules.payment_problem('finance_officer', expense('approved')))
        self.assertIsNotNone(rules.payment_problem('pastor', expense('approved')))
        self.assertIsNotNone(rules.payment_problem('admin', expense('submitted')))
        self.assertIsNone(rules.reversal_problem('admin', expense('paid')))
        self.assertIsNotNone(rules.reversal_problem('finance_officer', expense('paid')))
        self.assertIsNotNone(rules.reversal_problem('admin', expense('approved')))

    def test_budget_levels(self):
        self.assertEqual(rules.budget_status(1000, 500)['level'], 'ok')
        self.assertEqual(rules.budget_status(1000, 800)['level'], 'warning')
        status = rules.budget_status(1000, 1200)
        self.assertEqual((status['level'], status['percent'], status['remaining']), ('over', 120.0, -200.0))
        self.assertEqual(rules.budget_status(0, 50)['level'], 'over')
        self.assertEqual(rules.budget_status(0, 0)['level'], 'ok')

    def test_receipt_checks(self):
        self.assertIsNone(rules.check_receipt('', 'x.jpg'))
        self.assertEqual(rules.check_receipt('aGVsbG8=', 'bill 1.JPG'), 'bill 1.JPG')
        with self.assertRaises(ValueError):
            rules.check_receipt('aGVsbG8=', 'run.exe')
        with self.assertRaises(ValueError):
            rules.check_receipt('<script>', 'a.png')
        with self.assertRaises(ValueError):
            rules.check_receipt('A' * (8 * 1024 * 1024), 'big.jpg')

    def test_request_keys(self):
        self.assertIsNone(rules.request_key(''))
        self.assertEqual(rules.request_key('a' * 24), 'a' * 24)
        with self.assertRaises(ValueError):
            rules.request_key('short')


def staff(role='pastor', sid=7, active=True):
    return types.SimpleNamespace(id=sid, name='Sample Staff', staff_role=role, active=active,
                                 is_app_active=True, _fields={'is_app_active': True},
                                 user_id=types.SimpleNamespace(tz='Asia/Karachi'))


class EntryPointTests(unittest.TestCase):
    def model(self, person):
        model = expense_models.ChurchExpense()
        model.env = MagicMock()
        model.env['hr.employee'].sudo().browse().exists.return_value = person
        model.env.cr.savepoint.side_effect = lambda: nullcontext()
        return model

    def test_non_finance_roles_and_bad_ids_are_denied(self):
        for person in (staff('doctor'), staff('nurse'), staff(active=False)):
            result = self.model(person).app_church_finance(7, 'home')
            self.assertEqual(result['code'], 'denied')
        for bad in (None, True, '7', 0):
            self.assertEqual(self.model(staff()).app_church_finance(bad, 'home')['code'], 'denied')

    def test_pastor_cannot_open_budgets_funds_reports_or_limits(self):
        for action in ('budget', 'budget_save', 'funds', 'report', 'category_save', 'set_limit'):
            result = self.model(staff('pastor')).app_church_finance(7, action, {'year': 2026, 'lines': []})
            self.assertEqual(result['code'], 'denied', action)

    def test_only_admin_changes_the_approval_limit(self):
        result = self.model(staff('finance_officer')).app_church_finance(7, 'set_limit', {'limit': 1})
        self.assertEqual(result['code'], 'denied')

    def test_unknown_action_and_bad_payload(self):
        model = self.model(staff('admin'))
        self.assertEqual(model.app_church_finance(7, 'drop_all')['code'], 'invalid')
        self.assertEqual(model.app_church_finance(7, 'home', ['x'])['code'], 'invalid')


if __name__ == '__main__':
    unittest.main()
