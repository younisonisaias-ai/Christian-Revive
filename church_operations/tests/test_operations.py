"""Run on a staging Odoo 19 DB with --test-tags /church_operations."""
from uuid import uuid4
from odoo.tests import TransactionCase, tagged

@tagged('post_install', '-at_install')
class ChurchOperationsTests(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ops = cls.env['church.operations']
        cls.admin = cls.env['hr.employee'].create({'name': 'Ops Test Admin', 'staff_role': 'admin', 'is_app_active': True})
        cls.pastor = cls.env['hr.employee'].create({'name': 'Ops Test Pastor', 'staff_role': 'pastor', 'is_app_active': True})
        cls.person = cls.env['res.partner'].create({'name': 'Ops Test Member', 'is_member': True})
        cls.env['pastor.assignment'].create({'pastor_id': cls.pastor.id, 'member_id': cls.person.id})

    def call(self, action, data=None, staff=None):
        return self.ops.app_church_operations((staff or self.admin).id, action, data or {})

    def test_request_retry_creates_one_task_and_rechecks_access(self):
        data = {'request_key': uuid4().hex, 'member_id': self.person.id, 'name': 'Call member',
            'owner_id': self.pastor.id, 'kind': 'follow_up', 'due_date': '2026-10-20'}
        first, second = self.call('save_task', data), self.call('save_task', data)
        self.assertTrue(first['success'], first)
        self.assertEqual(first, second)
        self.assertEqual(self.env['church.ops.task'].search_count([('id', '=', first['task']['id'])]), 1)
        self.admin.is_app_active = False
        self.assertEqual(self.call('save_task', data)['code'], 'denied')

    def test_directory_and_care_are_scoped(self):
        outsider = self.env['res.partner'].create({'name': 'Ops Outsider', 'is_member': True})
        response = self.call('directory', staff=self.pastor)
        ids = [r['id'] for r in response['rows']]
        self.assertIn(self.person.id, ids)
        self.assertNotIn(outsider.id, ids)
        self.assertEqual(self.call('timeline', {'member_id': outsider.id}, self.pastor)['code'], 'denied')
        self.assertEqual(self.call('finance', staff=self.pastor)['code'], 'denied')

    def test_duplicates_need_explicit_confirmation(self):
        self.person.write({'email': 'ops-duplicate@example.invalid'})
        payload = {'request_key': uuid4().hex, 'name': 'Different name', 'email': 'ops-duplicate@example.invalid'}
        self.assertTrue(self.call('create_member', payload)['duplicate'])
        payload.update(request_key=uuid4().hex, confirm_duplicate=True)
        result = self.call('create_member', payload)
        self.assertTrue(result['success'], result)
        self.assertNotEqual(result['member_id'], self.person.id)

    def test_reconciliation_refund_and_receipt_share_net_amount(self):
        category = self.env['church.give.category'].search([], limit=1)
        if not category:
            category = self.env['church.give.category'].create({'name': 'Ops Test', 'code': 'ops_test'})
        tx = self.env['church.give.transaction'].create({'partner_id': self.person.id, 'amount': 100,
            'currency': 'PKR', 'state': 'completed', 'category_id': category.id, 'gateway': 'cash'})
        result = self.call('reconcile', {'request_key': uuid4().hex, 'transaction_id': tx.id,
            'amount': 100, 'currency': 'PKR', 'reference': 'TEST-PAYMENT'})
        self.assertTrue(result.get('matched'), result)
        refund = {'request_key': uuid4().hex, 'transaction_id': tx.id, 'amount': 30,
            'reference': 'TEST-REFUND', 'reason': 'Fixture correction'}
        self.assertTrue(self.call('refund', refund)['success'])
        self.assertTrue(self.call('refund', refund)['success'])
        self.assertEqual(len(tx.church_refund_ids), 1)
        receipt = self.call('receipt', {'transaction_id': tx.id})['receipt']
        self.assertEqual(receipt['net'], 70)
        self.assertEqual(receipt['refunded'], 30)
        self.assertFalse(self.call('refund', dict(refund, request_key=uuid4().hex, amount=71))['success'])
