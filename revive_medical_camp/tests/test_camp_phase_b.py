import base64
import uuid
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged

from .test_camp_flow import TestCampFlow

# A 1x1 PNG
PNG = base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082')).decode()


def _uuid():
    return str(uuid.uuid4())


@tagged('post_install', '-at_install')
class TestCampPhaseB(TestCampFlow):
    """Eye checks and glasses, photos, pregnancy checks, vaccines, stock
    planning and team planning."""

    def api(self, user):
        return self.env['camp.api'].with_user(user)

    def test_eye_check_gives_glasses(self):
        glasses = self.env['camp.glasses'].create({'camp_id': self.camp.id, 'kind': 'reading', 'power': 2.0,
                                                   'quantity': 2})
        _p, visit = self._register('Eye Esther')
        boot = self.api(self.nurse).bootstrap(self.camp.id)
        self.assertEqual(boot['glasses'][0]['quantity'], 2, 'nurses have the eye station by default')
        res = self.api(self.nurse).sync(self.camp.id, {'eye_exams': [{
            'client_uuid': _uuid(), 'visit': visit.client_uuid, 'va_right': '6/9', 'va_left': '6/18',
            'reading_power': 2.0, 'findings': 'cataract', 'needs_specialist': True, 'glasses_id': glasses.id}]})
        self.assertEqual(res['results']['eye_exams'][0]['status'], 'created')
        self.assertEqual(glasses.quantity, 1)
        self.assertEqual(visit.eye_exam_ids.va_right, '6/9')
        # Registration staff cannot do eye checks.
        bad = self.api(self.registration).sync(self.camp.id, {'eye_exams': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid}]})
        self.assertEqual(bad['results']['eye_exams'][0]['status'], 'error')

    def test_photo_needs_consent(self):
        _p, visit = self._register('Photo Parveen')
        ok = self.api(self.doctor).sync(self.camp.id, {'photos': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'image': PNG, 'note': 'Leg ulcer', 'consent': True}]})
        self.assertEqual(ok['results']['photos'][0]['status'], 'created')
        self.assertTrue(visit.photo_ids.image)
        no = self.api(self.doctor).sync(self.camp.id, {'photos': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'image': PNG, 'consent': False}]})
        self.assertEqual(no['results']['photos'][0]['status'], 'error')

    def test_pregnancy_danger_sign_makes_urgent(self):
        _p, visit = self._register('Mother Mehwish')
        self.api(self.nurse).sync(self.camp.id, {'anc_checks': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'weeks': 34, 'danger_signs': 'headache,swelling'}]})
        self.assertEqual((visit.priority, visit.pregnant), ('urgent', True))
        self.assertTrue(visit.anc_check_ids.high_risk)

    def test_child_vaccines(self):
        _p, visit = self._register('Baby Bilal', age_years=0)
        self.api(self.nurse).sync(self.camp.id, {'vaccine_records': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'vaccine': 'penta1', 'status': 'had', 'age_months': 5},
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'vaccine': 'penta2', 'status': 'missed',
             'age_months': 5}]})
        self.assertEqual(sorted(visit.vaccine_record_ids.mapped('status')), ['had', 'missed'])
        # Changing a status updates the same record.
        self.api(self.nurse).sync(self.camp.id, {'vaccine_records': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'vaccine': 'penta2', 'status': 'given'}]})
        self.assertEqual(len(visit.vaccine_record_ids), 2)
        self.env['camp.team.member'].create({'camp_id': self.camp.id, 'user_id': self.coordinator.id,
                                             'role': 'coordinator'})
        summary = self.api(self.coordinator).camp_summary(self.camp.id)
        self.assertEqual(summary['vaccines_given'], 1)

    def test_stock_plan_and_return(self):
        # A closed earlier camp used 4 tablets for 2 patients -> 200 per 100 patients.
        old = self.env['camp.camp'].create({'name': 'Old Camp', 'state': 'running'})
        self.env['stock.quant']._update_available_quantity(self.medicine, old.stock_location_id, 50,
                                                           lot_id=self.lot_later)
        for name in ('One', 'Two'):
            p = self.env['camp.patient'].create({'name': name, 'sex': 'male', 'age_years': 30, 'consent_care': True})
            v = self.env['camp.visit'].create({'camp_id': old.id, 'patient_id': p.id})
            c = self.env['camp.consultation'].create({
                'visit_id': v.id, 'doctor_id': self.doctor.id,
                'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'quantity': 2})]})
            c.action_finish()
            c.prescription_line_ids.action_dispense()
        old.action_close()
        new = self.env['camp.camp'].create({'name': 'New Camp', 'expected_patients': 100,
                                            'date_start': fields.Date.today() + timedelta(days=10)})
        plan = self.env['camp.stock.plan'].with_context(active_id=new.id).create({})
        line = plan.line_ids.filtered(lambda l: l.formulary_id == self.formulary)
        self.assertEqual((line.per_100, line.suggested, line.to_send), (200, 240, 240))
        action = plan.action_create_transfer()
        picking = self.env['stock.picking'].browse(action['res_id'])
        self.assertEqual(picking.location_dest_id, new.stock_location_id)
        self.assertEqual(picking.move_ids.product_uom_qty, 240)
        # After the old camp: return what is left.
        back = self.env['stock.picking'].browse(old.action_return_leftovers()['res_id'])
        self.assertEqual(back.location_id, old.stock_location_id)
        self.assertEqual(back.move_ids.product_uom_qty, 46)

    def test_team_planning(self):
        self.doctor.camp_pmdc_expiry = fields.Date.today() - timedelta(days=1)
        soon = self.env['camp.camp'].create({'name': 'Tomorrow Camp', 'state': 'ready', 'site': 'Church hall',
                                             'date_start': fields.Date.today() + timedelta(days=1)})
        member = self.env['camp.team.member'].create({'camp_id': soon.id, 'user_id': self.doctor.id,
                                                      'role': 'doctor', 'phone': '03001234567',
                                                      'shift_start': 8.0, 'shift_end': 14.5})
        self.assertIn('expired', member.pmdc_warning)
        self.assertTrue(member.can_eye)
        self.env['camp.reminder']._generate(soon)
        reminder = self.env['camp.reminder'].search([('team_member_id', '=', member.id)])
        self.assertEqual(reminder.kind, 'team_shift')
        self.assertIn('8:00–14:30', reminder.message)
        self.assertEqual(reminder.phone, '03001234567')
        boot = self.api(self.doctor).bootstrap(soon.id)
        self.assertEqual(boot['me']['pmdc_expiry'], fields.Date.to_string(self.doctor.camp_pmdc_expiry))
        me = next(m for m in boot['team'] if m['id'] == member.id)
        self.assertEqual((me['shift_start'], me['shift_end']), (8.0, 14.5))
