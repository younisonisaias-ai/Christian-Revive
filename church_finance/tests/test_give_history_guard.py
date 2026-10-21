from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGiveHistoryGuard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env['res.partner']
        cls.member = Partner.create({'name': 'Giver One', 'is_member': True})
        cls.other = Partner.create({'name': 'Giver Two', 'is_member': True})
        Session = cls.env['church.app.session']
        cls.member_token = Session._issue('member', partner=cls.member)
        cls.staff = cls.env['hr.employee'].create({
            'name': 'Finance Admin', 'staff_role': 'admin', 'is_app_active': True,
            'app_email': 'finance-admin@example.invalid', 'app_pin': '9999'})
        cls.staff_token = Session._issue('staff', employee=cls.staff)

    def allowed(self, uid, **ctx):
        return self.env['church.give.transaction'].with_context(**ctx)._app_history_allowed(
            app_user_id=uid)

    def test_no_id_lists_nothing(self):
        self.assertFalse(self.allowed(''))
        self.assertFalse(self.allowed('guest'))
        self.assertEqual(self.env['church.give.transaction'].app_get_transactions(limit=5), [])

    def test_member_sees_only_own_history(self):
        token = {'app_session_token': self.member_token}
        self.assertTrue(self.allowed(str(self.member.id), **token))
        self.assertFalse(self.allowed(str(self.other.id), **token))

    def test_staff_may_read_for_reports(self):
        self.assertTrue(self.allowed(str(self.other.id), app_staff_session_token=self.staff_token))

    def test_without_token_only_until_sessions_are_required(self):
        self.assertTrue(self.allowed(str(self.member.id)))
        self.env['ir.config_parameter'].sudo().set_param('church_management.require_app_session', 'True')
        self.assertFalse(self.allowed(str(self.member.id)))
