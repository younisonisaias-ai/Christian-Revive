from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestVisitRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Partner = env['res.partner']
        cls.family = env['church.family'].create({'name': 'Gill Family'})
        cls.member = Partner.create({'name': 'Sara Gill', 'is_member': True, 'family_id': cls.family.id,
                                     'street': '12 Church Road', 'city': 'Lahore'})
        cls.mother = Partner.create({'name': 'Mother Gill', 'is_member': True, 'family_id': cls.family.id})
        cls.stranger = Partner.create({'name': 'Not Family', 'is_member': True})
        Employee = env['hr.employee']
        cls.pastor = Employee.create({'name': 'Pastor Assigned', 'staff_role': 'pastor', 'is_app_active': True,
                                      'app_email': 'assigned@example.invalid', 'app_pin': '1111'})
        cls.other_pastor = Employee.create({'name': 'Pastor Other', 'staff_role': 'pastor',
                                            'is_app_active': True, 'app_email': 'other@example.invalid',
                                            'app_pin': '2222'})
        env['pastor.assignment'].create({'pastor_id': cls.pastor.id, 'member_id': cls.mother.id})
        env['pastor.assignment'].create({'pastor_id': cls.other_pastor.id, 'member_id': cls.stranger.id})
        Session = env['church.app.session']
        cls.member_token = Session._issue('member', partner=cls.member)
        cls.pastor_token = Session._issue('staff', employee=cls.pastor)
        cls.other_token = Session._issue('staff', employee=cls.other_pastor)

    def as_member(self):
        return self.env['church.visit.request'].with_context(app_session_token=self.member_token)

    def as_pastor(self, other=False):
        return self.env['church.visit.request'].with_context(
            app_staff_session_token=self.other_token if other else self.pastor_token)

    def ask(self, **vals):
        vals.setdefault('member_id', self.mother.id)
        vals.setdefault('reason', 'hospital')
        vals.setdefault('place', 'hospital')
        vals.setdefault('address', 'Mayo Hospital, ward 4')
        return self.as_member().app_request_visit(vals, requester_partner_id=self.member.id)

    def test_options_list_household_with_address(self):
        people = self.as_member().app_visit_options(requester_partner_id=self.member.id)['people']
        self.assertEqual(people[0]['name'], 'Sara Gill')
        self.assertEqual(people[0]['address'], '12 Church Road, Lahore')
        self.assertIn('Mother Gill', [p['name'] for p in people])

    def test_request_for_family_goes_to_their_pastor(self):
        tomorrow = fields.Date.to_string(fields.Date.today() + timedelta(days=1))
        result = self.ask(preferred=[{'date': tomorrow, 'part': 'evening'}], is_urgent=True)
        self.assertTrue(result['success'])
        request = result['request']
        self.assertEqual(request['pastor_id'], self.pastor.id)
        self.assertEqual(request['preferred'], [{'date': tomorrow, 'part': 'evening'}])
        open_ = self.as_pastor().app_visit_requests(requester_staff_id=self.pastor.id)['requests']
        self.assertEqual([r['id'] for r in open_], [request['id']])
        # Another associate pastor does not see it.
        other = self.as_pastor(other=True).app_visit_requests(requester_staff_id=self.other_pastor.id)
        self.assertEqual(other['requests'], [])

    def test_cannot_ask_for_someone_outside_the_household(self):
        self.assertFalse(self.ask(member_id=self.stranger.id)['success'])
        self.assertFalse(self.ask(place='hospital', address='')['success'])

    def test_schedule_then_visit_records_a_care_note(self):
        request = self.ask()['request']
        Pastor = self.as_pastor()
        when = fields.Datetime.to_string(fields.Datetime.now() + timedelta(days=2))
        scheduled = Pastor.app_schedule_visit(request['id'], when, 'See you then',
                                              requester_staff_id=self.pastor.id)
        self.assertEqual(scheduled['request']['state'], 'scheduled')
        done = Pastor.app_complete_visit(request['id'], 'Prayed together',
                                         requester_staff_id=self.pastor.id)
        self.assertEqual(done['request']['state'], 'visited')
        record = self.env['church.visit.request'].browse(request['id'])
        self.assertEqual(record.care_note_id.note_type, 'hospital')
        self.assertEqual(record.care_note_id.member_id, self.mother)
        mine = self.as_member().app_my_visit_requests(requester_partner_id=self.member.id)['requests']
        self.assertEqual(mine[0]['state'], 'visited')

    def test_other_pastor_cannot_act_and_member_can_cancel(self):
        request = self.ask()['request']
        refused = self.as_pastor(other=True).app_decline_visit(
            request['id'], 'Busy', requester_staff_id=self.other_pastor.id)
        self.assertFalse(refused['success'])
        cancelled = self.as_member().app_cancel_visit(request['id'], requester_partner_id=self.member.id)
        self.assertEqual(cancelled['request']['state'], 'cancelled')
        self.assertFalse(self.as_member().app_cancel_visit(
            request['id'], requester_partner_id=self.member.id)['success'])
