from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChurchPlan(TransactionCase):

    def set_plan(self, plan, **addons):
        Param = self.env['ir.config_parameter'].sudo()
        Param.set_param('church_management.plan', plan)
        for name in ('giving', 'books'):
            Param.set_param('church_management.addon_%s' % name, 'True' if addons.get(name) else 'False')

    def test_default_is_enterprise(self):
        self.env['ir.config_parameter'].sudo().set_param('church_management.plan', False)
        self.assertEqual(self.env['church.plan']._plan(), 'enterprise')
        self.assertTrue(self.env['church.plan']._allows('enterprise'))

    def test_enterprise_features_refused_on_premium(self):
        self.set_plan('premium')
        result = self.env['cell.group'].app_get_cell_groups(requester_partner_id=1)
        self.assertEqual(result.get('code'), 'plan')
        # Premium features still work (the call gets past the plan check).
        visits = self.env['church.visit.request'].app_my_visit_requests(requester_partner_id=0)
        self.assertNotEqual(visits.get('code'), 'plan')

    def test_basic_refuses_church_management(self):
        self.set_plan('basic')
        self.assertEqual(self.env['res.partner'].app_get_members(requester_staff_id=0).get('code'), 'plan')
        # Sign-in endpoints are Basic.
        self.assertNotEqual(self.env['church.app.session'].app_session_policy().get('code'), 'plan')

    def test_giving_add_on(self):
        Plan = self.env['church.plan']
        self.set_plan('basic')
        self.assertFalse(Plan._allows('giving'))
        if 'church.give.transaction' in self.env:
            self.assertEqual(self.env['church.give.transaction'].app_get_transactions(app_user_id='5'), [])
        self.set_plan('basic', giving=True)
        self.assertTrue(Plan._allows('giving'))
        self.set_plan('premium')
        self.assertTrue(Plan._allows('giving'))
        self.assertFalse(Plan._allows('books'))
        self.set_plan('premium', books=True)
        self.assertTrue(Plan._allows('books'))
