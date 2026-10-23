from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestChurchLocationApp(TransactionCase):

    def setUp(self):
        super().setUp()
        Employee = self.env['hr.employee']
        self.admin = Employee.create({'name': 'Loc Admin', 'staff_role': 'admin', 'is_app_active': True})
        self.associate = Employee.create({'name': 'Loc Associate', 'staff_role': 'pastor',
                                          'is_senior_pastor': False, 'is_app_active': True})
        self.Location = self.env['church.location']
        self.service = self.env['church.service'].create({
            'name': 'Field Service', 'date_start': '2026-11-01 05:00:00'})

    def as_staff(self, employee):
        session = self.env['church.app.session'].new({'employee_id': employee.id})
        return patch.object(type(self.env['church.app.session']), '_current_staff', return_value=session)

    def test_admin_marks_a_new_location(self):
        with self.as_staff(self.admin):
            res = self.Location.app_save_church_location(
                {'name': 'Hall  B', 'latitude': 24.8655, 'longitude': 67.0274, 'radius_m': 150})
        self.assertTrue(res['success'], res)
        loc = self.Location.browse(res['location']['location_id'])
        self.assertEqual(loc.name, 'Hall B')
        self.assertAlmostEqual(loc.latitude, 24.8655, places=4)
        self.assertEqual(loc.geofence_radius_m, 150)
        self.assertTrue(loc.location_validation_enabled)

    def test_admin_moves_a_location_and_sets_a_service(self):
        loc = self.Location.create({'name': 'Old Spot', 'latitude': 1.0, 'longitude': 1.0})
        with self.as_staff(self.admin):
            res = self.Location.app_save_church_location(
                {'latitude': 24.86, 'longitude': 67.02, 'radius_m': 200}, location_id=loc.id)
            self.assertTrue(res['success'], res)
            res = self.Location.app_set_service_location(self.service.id, loc.id)
        self.assertTrue(res['success'], res)
        self.assertEqual(loc.name, 'Old Spot')
        self.assertEqual(loc.geofence_radius_m, 200)
        self.assertEqual(self.service.location_id, loc)

    def test_associate_pastor_can_list_but_not_change(self):
        with self.as_staff(self.associate):
            listed = self.Location.app_church_locations()
            saved = self.Location.app_save_church_location(
                {'name': 'Nope', 'latitude': 24.8, 'longitude': 67.0})
        self.assertTrue(listed['success'])
        self.assertFalse(listed['can_edit'])
        self.assertFalse(saved['success'])

    def test_bad_radius_and_no_session_are_refused(self):
        with self.as_staff(self.admin):
            res = self.Location.app_save_church_location(
                {'name': 'Too Big', 'latitude': 24.8, 'longitude': 67.0, 'radius_m': 99999})
        self.assertFalse(res['success'])
        self.assertFalse(self.Location.app_church_locations()['success'])
