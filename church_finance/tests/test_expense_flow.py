from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestExpenseFlow(TransactionCase):
    """End-to-end expense flow through the same entry point the app uses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Employee = cls.env['hr.employee'].sudo()
        extra = {'is_app_active': True} if 'is_app_active' in Employee._fields else {}

        def person(name, role):
            return Employee.create(dict(extra, name=name, staff_role=role))
        cls.admin = person('Test Admin', 'admin')
        cls.finance = person('Test Finance', 'finance_officer')
        cls.pastor = person('Test Pastor', 'pastor')
        cls.category = cls.env['church.expense.category'].sudo().create({'name': 'Test utilities'})
        cls.Expense = cls.env['church.expense']

    def call(self, who, action, **payload):
        return self.Expense.app_church_finance(who.id, action, payload)

    def record(self, who, amount, **extra):
        result = self.call(who, 'save', category_id=self.category.id, description='Electricity bill',
                           amount=amount, submit=True, **extra)
        self.assertTrue(result['success'], result)
        return result['expense']['id']

    def test_full_flow_and_budget(self):
        expense_id = self.record(self.pastor, '12000')
        # Pastors can see their own expense but cannot approve it.
        self.assertEqual(self.call(self.pastor, 'approve', id=expense_id)['code'], 'denied')
        self.assertTrue(self.call(self.finance, 'approve', id=expense_id)['success'])
        self.assertEqual(self.call(self.pastor, 'pay', id=expense_id, method='cash')['code'], 'denied')
        paid = self.call(self.finance, 'pay', id=expense_id, method='cash')
        self.assertEqual(paid['expense']['state'], 'paid')
        year = self.Expense.browse(expense_id).date.year
        saved = self.call(self.finance, 'budget_save', year=year,
                          lines=[{'category_id': self.category.id, 'amount': '13000'}])
        line = next(l for l in saved['lines'] if l['category_id'] == self.category.id)
        self.assertEqual((line['actual'], line['level']), (12000.0, 'warning'))
        # Paid expenses are locked; only an Admin reverses them.
        with self.assertRaises(Exception):
            self.Expense.browse(expense_id).write({'amount': 1})
        self.assertEqual(self.call(self.finance, 'reverse', id=expense_id, reason='Duplicate')['code'], 'denied')
        self.assertTrue(self.call(self.admin, 'reverse', id=expense_id, reason='Duplicate bill')['success'])
        line = next(l for l in self.call(self.admin, 'budget', year=year)['lines']
                    if l['category_id'] == self.category.id)
        self.assertEqual(line['actual'], 0.0)

    def test_limits_and_self_approval(self):
        big = self.record(self.pastor, '75000')
        self.assertEqual(self.call(self.finance, 'approve', id=big)['code'], 'denied')
        self.assertTrue(self.call(self.admin, 'approve', id=big)['success'])
        own = self.record(self.finance, '100')
        self.assertEqual(self.call(self.finance, 'approve', id=own)['code'], 'denied')

    def test_pastor_sees_only_own_and_retry_is_not_duplicated(self):
        other = self.record(self.finance, '500')
        self.assertEqual(self.call(self.pastor, 'get', id=other)['code'], 'denied')
        payload = dict(category_id=self.category.id, description='Bus hire', amount='3000',
                       request_key='k' * 24)
        first = self.call(self.pastor, 'save', **payload)
        second = self.call(self.pastor, 'save', **payload)
        self.assertEqual(first['expense']['id'], second['expense']['id'])
        self.assertTrue(second.get('replayed'))

    def test_rejected_expense_can_be_corrected_and_resubmitted(self):
        expense_id = self.record(self.pastor, '2000')
        self.assertEqual(self.call(self.finance, 'reject', id=expense_id)['code'], 'invalid')
        self.assertTrue(self.call(self.finance, 'reject', id=expense_id, reason='Attach the bill')['success'])
        fixed = self.call(self.pastor, 'save', id=expense_id, category_id=self.category.id,
                          description='Electricity bill', amount='2100', submit=True)
        self.assertEqual(fixed['expense']['state'], 'submitted')
