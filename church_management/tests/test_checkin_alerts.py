from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCheckinAlerts(TransactionCase):

    def setUp(self):
        super().setUp()
        Employee = self.env['hr.employee']
        self.admin = Employee.create({'name': 'Alert Admin', 'staff_role': 'admin',
                                      'is_app_active': True, 'app_fcm_token': 'tok-admin'})
        self.pastor = Employee.create({'name': 'Alert Pastor', 'staff_role': 'pastor', 'is_senior_pastor': False,
                                       'is_app_active': True, 'app_fcm_token': 'tok-pastor'})
        self.other = Employee.create({'name': 'Other Pastor', 'staff_role': 'pastor', 'is_senior_pastor': False,
                                      'is_app_active': True, 'app_fcm_token': 'tok-other'})
        Partner = self.env['res.partner']
        self.head = Partner.create({'name': 'Alert Head'})
        self.son = Partner.create({'name': 'Alert Son'})
        self.env['pastor.assignment'].create({'member_id': self.head.id, 'pastor_id': self.pastor.id})
        self.service = self.env['church.service'].create({'name': 'Alert Service', 'date_start': '2026-11-01 05:00:00'})
        self.Attendance = self.env['church.event.attendance']

    def test_one_alert_to_admin_and_assigned_pastor(self):
        rows = [
            {'member_id': self.head.id, 'member_name': 'Alert Head', 'service_id': self.service.id, 'is_late': False},
            {'member_id': self.son.id, 'member_name': 'Alert Son', 'service_id': self.service.id, 'is_late': True},
        ]
        with patch('odoo.addons.church_management.models.checkin_alerts._send_fcm') as send:
            self.Attendance._alert_staff_check_in(self.head, rows)
            self.env.cr.postcommit.run()
        self.assertEqual(send.call_count, 1)
        _sa, tokens, title, body, data = send.call_args.args
        self.assertEqual(set(tokens) & {'tok-admin', 'tok-pastor', 'tok-other'}, {'tok-admin', 'tok-pastor'})
        self.assertEqual(title, 'Checked in: Alert Head +1 family')
        self.assertIn('Alert Service', body)
        self.assertIn('late', body)
        self.assertEqual(data['kind'], 'checkin')
