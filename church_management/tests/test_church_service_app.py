from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChurchServiceApp(TransactionCase):

    def setUp(self):
        super().setUp()
        Employee = self.env['hr.employee']
        self.admin = Employee.create({'name': 'Svc Admin', 'staff_role': 'admin', 'is_app_active': True})
        self.associate = Employee.create({'name': 'Svc Associate', 'staff_role': 'pastor',
                                          'is_senior_pastor': False, 'is_app_active': True})
        self.Service = self.env['church.service']
        self.place = self.env['church.location'].create({'name': 'Svc Hall', 'latitude': 24.86, 'longitude': 67.02})

    def as_staff(self, employee):
        session = self.env['church.app.session'].new({'employee_id': employee.id})
        return patch.object(type(self.env['church.app.session']), '_current_staff', return_value=session)

    def test_admin_creates_edits_and_cancels(self):
        with self.as_staff(self.admin):
            res = self.Service.app_save_service({
                'name': 'Youth  Night', 'service_type': 'youth',
                'date_start': '2026-11-02 13:00:00', 'date_end': '2026-11-02 15:00:00',
                'location_id': self.place.id, 'geofence_required': False})
            self.assertTrue(res['success'], res)
            service = self.Service.browse(res['service']['service_id'])
            self.assertEqual(service.name, 'Youth Night')
            self.assertEqual(service.service_type, 'youth')
            self.assertEqual(service.location_id, self.place)
            self.assertFalse(service.geofence_required)
            self.assertTrue(service.smart_checkin_enabled)
            self.assertTrue(service.is_active)

            res = self.Service.app_save_service(
                {'name': 'Youth Night', 'date_start': '2026-11-02 14:00:00', 'location_id': False},
                service_id=service.id)
            self.assertTrue(res['success'], res)
            self.assertFalse(service.location_id)
            self.assertEqual(str(service.date_start), '2026-11-02 14:00:00')

            self.assertTrue(self.Service.app_cancel_service(service.id)['success'])
            self.assertTrue(service.cancelled)
            listed = self.Service.app_admin_services(days_back=400, days_ahead=366)
        self.assertTrue(listed['can_edit'])
        self.assertIn(service.id, [s['service_id'] for s in listed['services']])

    def test_bad_times_are_refused(self):
        with self.as_staff(self.admin):
            res = self.Service.app_save_service(
                {'name': 'Backwards', 'date_start': '2026-11-02 15:00:00', 'date_end': '2026-11-02 13:00:00'})
        self.assertFalse(res['success'])

    def test_associate_pastor_cannot_change(self):
        with self.as_staff(self.associate):
            res = self.Service.app_save_service({'name': 'Nope', 'date_start': '2026-11-02 13:00:00'})
            listed = self.Service.app_admin_services()
        self.assertFalse(res['success'])
        self.assertTrue(listed['success'])
        self.assertFalse(listed['can_edit'])

    def test_notify_failure_still_saves(self):
        with self.as_staff(self.admin), \
                patch.object(type(self.env['revive.notification']), 'action_send', side_effect=Exception('no FCM')):
            res = self.Service.app_save_service(
                {'name': 'Notified', 'date_start': '2026-11-03 13:00:00'}, notify=True)
        self.assertTrue(res['success'], res)
        self.assertFalse(res['notified'])
