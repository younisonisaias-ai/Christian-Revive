from unittest.mock import patch

from werkzeug.security import generate_password_hash

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAccountDeletion(TransactionCase):

    def setUp(self):
        super().setUp()
        Partner = self.env['res.partner']
        self.member = Partner.create({
            'name': 'Keep Member', 'is_member': True, 'email': 'keep@example.com',
            'is_app_profile': True, 'app_login_email': 'keep@example.com',
            'app_password_hash': generate_password_hash('secret1'), 'app_fcm_token': 'tok'})
        self.app_only = Partner.create({
            'name': 'App Only', 'email': 'only@example.com', 'phone': '0300',
            'is_app_profile': True, 'app_login_email': 'only@example.com',
            'app_password_hash': generate_password_hash('secret2')})
        self.Data = self.env['church.member.app.data']

    def as_member(self, partner):
        session = self.env['church.app.session'].new({'partner_id': partner.id, 'kind': 'member'})
        return patch.object(type(self.env['church.app.session']), '_current_member', return_value=session)

    def test_wrong_password_changes_nothing(self):
        with self.as_member(self.member):
            res = self.env['res.partner'].app_delete_account('nope')
        self.assertFalse(res['success'])
        self.assertTrue(self.member.is_app_profile)

    def test_member_loses_login_and_app_data_but_church_keeps_record(self):
        self.Data.create({'partner_id': self.member.id, 'key': 'music', 'value': '{}'})
        with self.as_member(self.member):
            res = self.env['res.partner'].app_delete_account('secret1')
        self.assertTrue(res['success'], res)
        self.assertTrue(res['kept_church_records'])
        self.assertFalse(self.member.is_app_profile)
        self.assertFalse(self.member.app_login_email)
        self.assertFalse(self.member.app_password_hash)
        self.assertFalse(self.member.app_fcm_token)
        self.assertFalse(self.Data.search([('partner_id', '=', self.member.id)]))
        self.assertEqual(self.member.name, 'Keep Member')
        self.assertTrue(self.member.active)
        # The same login no longer works.
        self.assertFalse(self.env['res.partner'].app_login('keep@example.com', 'secret1')['success'])

    def test_app_only_user_is_anonymised(self):
        with self.as_member(self.app_only):
            res = self.env['res.partner'].app_delete_account('secret2')
        self.assertTrue(res['success'], res)
        self.assertFalse(res['kept_church_records'])
        partner = self.app_only.with_context(active_test=False)
        self.assertEqual(partner.name, 'Deleted app user')
        self.assertFalse(partner.email)
        self.assertFalse(partner.phone)
        self.assertFalse(partner.active)
