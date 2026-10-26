from datetime import date, timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRepeatingServices(TransactionCase):

    def schedule(self, **vals):
        vals.setdefault('name', 'Test service')
        vals.setdefault('weekday', '6')  # Sunday
        return self.env['church.service.schedule'].create(vals)

    def test_monthly_first_and_last_sunday(self):
        Schedule = self.env['church.service.schedule']
        self.assertEqual(Schedule._nth_weekday(2026, 11, 6, '1'), date(2026, 11, 1))
        self.assertEqual(Schedule._nth_weekday(2026, 11, 6, 'last'), date(2026, 11, 29))
        self.assertEqual(Schedule._nth_weekday(2026, 12, 4, 'last'), date(2026, 12, 25))
        monthly = self.schedule(frequency='monthly', month_week='1')
        days = monthly._upcoming_days(date(2026, 10, 21))
        self.assertEqual(days[:2], [date(2026, 11, 1), date(2026, 12, 6)])

    def test_every_two_weeks_from_start_date(self):
        fortnight = self.schedule(frequency='fortnightly', start_date=date(2026, 10, 4), weeks_ahead=6)
        days = fortnight._upcoming_days(date(2026, 10, 21))
        self.assertEqual(days[:3], [date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 29)])

    def test_weekly_unchanged(self):
        # A fixed start date: left empty, it becomes the day the test runs.
        weekly = self.schedule(weeks_ahead=3, start_date=date(2026, 10, 4))
        self.assertEqual(weekly._upcoming_days(date(2026, 10, 21))[:3],
                         [date(2026, 10, 25), date(2026, 11, 1), date(2026, 11, 8)])


@tagged('post_install', '-at_install')
class TestCareFeatures(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        env['ir.config_parameter'].sudo().set_param('church_management.plan', 'enterprise')
        Partner = env['res.partner']
        cls.member = Partner.create({'name': 'Away Member', 'is_member': True, 'membership_status': 'member'})
        cls.regular = Partner.create({'name': 'Regular Member', 'is_member': True, 'membership_status': 'member'})
        cls.pastor = env['hr.employee'].create({
            'name': 'Pastor Care', 'staff_role': 'pastor', 'is_app_active': True,
            'app_email': 'care@example.invalid', 'app_pin': '5555', 'mobile_phone': '0300 0000000'})
        env['pastor.assignment'].create({'pastor_id': cls.pastor.id, 'member_id': cls.member.id})
        cls.token = env['church.app.session']._issue('staff', employee=cls.pastor)
        now = fields.Datetime.now()
        service = env['church.service'].create({'name': 'Old service', 'date_start': now - timedelta(days=30)})
        recent = env['church.service'].create({'name': 'This week', 'date_start': now - timedelta(days=2)})
        Attendance = env['church.event.attendance'].sudo()
        Attendance.create({'event_id': service.id, 'member_id': cls.member.id,
                           'check_in_time': now - timedelta(days=30)})
        Attendance.create({'event_id': recent.id, 'member_id': cls.regular.id,
                           'check_in_time': now - timedelta(days=2)})

    def test_absence_follow_up_once_a_month(self):
        Dashboard = self.env['church.dashboard']
        Dashboard._cron_absence_followups()
        notes = self.env['pastoral.care.note'].search([('member_id', '=', self.member.id)])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes.follow_up_assigned_to_id, self.pastor)
        self.assertFalse(self.env['pastoral.care.note'].search([('member_id', '=', self.regular.id)]))
        Dashboard._cron_absence_followups()
        self.assertEqual(self.env['pastoral.care.note'].search_count([('member_id', '=', self.member.id)]), 1)

    def test_member_care_info_and_prayer_team(self):
        Assignment = self.env['pastor.assignment'].with_context(app_staff_session_token=self.token)
        info = Assignment.app_member_care_info(self.member.id, requester_staff_id=self.pastor.id)
        self.assertEqual(info['pastor']['name'], 'Pastor Care')
        self.assertEqual(info['pastor']['phone'], '0300 0000000')
        self.assertFalse(info['prayer_team'])
        Partner = self.env['res.partner'].with_context(app_staff_session_token=self.token)
        self.assertTrue(Partner.app_set_prayer_team(self.member.id, True,
                                                    requester_staff_id=self.pastor.id)['prayer_team'])

    def test_pastor_week_and_care_report(self):
        Dashboard = self.env['church.dashboard'].with_context(app_staff_session_token=self.token)
        week = Dashboard.app_pastor_week(requester_staff_id=self.pastor.id)
        self.assertEqual(len(week['days']), 7)
        report = Dashboard.app_care_report(30, requester_staff_id=self.pastor.id)
        row = report['pastors'][0]
        self.assertEqual(row['members'], 1)
        self.assertEqual(row['not_contacted'], 1)

    def test_urgent_prayer_alerts_the_team_only_when_shared(self):
        self.member.write({'prayer_team': True, 'app_fcm_token': 'token-1'})
        Prayer = self.env['prayer.request']
        sent = []
        original = type(Prayer)._alert_prayer_team

        def spy(rec):
            sent.append(rec.subject)
            return original(rec)
        type(Prayer)._alert_prayer_team = spy
        try:
            Prayer.create({'name': 'Asker', 'subject': 'Shared', 'message': 'Please pray',
                           'urgency': 'urgent', 'visibility': 'public'})
            Prayer.create({'name': 'Asker', 'subject': 'Pastors only', 'message': 'Please pray',
                           'urgency': 'urgent', 'visibility': 'pastor'})
        finally:
            type(Prayer)._alert_prayer_team = original
        self.assertEqual(sent, ['Shared'])
