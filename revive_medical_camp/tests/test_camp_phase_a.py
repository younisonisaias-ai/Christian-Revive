import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from .test_camp_flow import TestCampFlow


def _uuid():
    return str(uuid.uuid4())


@tagged('post_install', '-at_install')
class TestCampPhaseA(TestCampFlow):
    """History across camps, lab tests, pre-registration, reminders,
    referral confirmation and duplicate merge."""

    def api(self, user):
        return self.env['camp.api'].with_user(user)

    def test_patient_history_across_camps(self):
        old = self.env['camp.camp'].create({'name': 'Spring Camp', 'state': 'running',
                                            'date_start': fields.Date.today() - timedelta(days=200)})
        patient = self.env['camp.patient'].create({'name': 'History Hamid', 'sex': 'male', 'age_years': 55,
                                                   'consent_care': True})
        v1 = self.env['camp.visit'].create({'camp_id': old.id, 'patient_id': patient.id})
        self.env['camp.vitals'].sudo().create({'visit_id': v1.id, 'bp_systolic': 170, 'bp_diastolic': 100,
                                               'blood_sugar': 210, 'weight': 80})
        self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': patient.id})
        row = next(p for p in self.api(self.doctor).bootstrap(self.camp.id)['patients'] if p['name'] == 'History Hamid')
        self.assertEqual(len(row['history']), 1)
        h = row['history'][0]
        self.assertEqual((h['camp_name'], h['bp_systolic'], h['blood_sugar']), ('Spring Camp', 170, 210))
        reg = next(p for p in self.api(self.registration).bootstrap(self.camp.id)['patients']
                   if p['name'] == 'History Hamid')
        self.assertNotIn('history', reg, 'registration does not see clinical history')

    def test_lab_order_round_trip(self):
        _p, visit = self._register('Lab Laila')
        o_uuid = _uuid()
        res = self.api(self.doctor).sync(self.camp.id, {'lab_orders': [
            {'client_uuid': o_uuid, 'visit': visit.client_uuid, 'test': 'pregnancy'}]})
        self.assertEqual(res['results']['lab_orders'][0]['status'], 'created')
        feed = self.api(self.nurse).changes(self.camp.id, since=None)
        self.assertEqual([o['state'] for o in feed['lab_orders'] if o['client_uuid'] == o_uuid], ['ordered'])
        # Only the lab desk (nurse) records results; a positive pregnancy test marks the visit.
        bad = self.api(self.registration).sync(self.camp.id, {'lab_orders': [
            {'client_uuid': o_uuid, 'result': 'positive'}]})
        self.assertEqual(bad['results']['lab_orders'][0]['status'], 'error')
        self.api(self.nurse).sync(self.camp.id, {'lab_orders': [
            {'client_uuid': o_uuid, 'result': 'Positive', 'abnormal': False}]})
        order = self.env['camp.lab.order'].search([('client_uuid', '=', o_uuid)])
        self.assertEqual((order.state, order.result), ('done', 'Positive'))
        self.assertTrue(visit.pregnant)
        # Calls to the lab desk show on the call screen.
        call = self.api(self.nurse).sync(self.camp.id, {'calls': [
            {'client_uuid': _uuid(), 'visit': visit.client_uuid, 'station': 'lab'}]})
        self.assertEqual(call['results']['calls'][0]['status'], 'updated')

    def test_pre_registration_then_arrival(self):
        self.camp.state = 'ready'
        p_uuid, v_uuid = _uuid(), _uuid()
        self.api(self.registration).sync(self.camp.id, {
            'patients': [{'client_uuid': p_uuid, 'name': 'Booked Bushra', 'sex': 'female', 'age_years': 40,
                          'consent_care': True}],
            'visits': [{'client_uuid': v_uuid, 'patient': p_uuid, 'state': 'booked', 'token_no': 5}]})
        visit = self.env['camp.visit'].search([('client_uuid', '=', v_uuid)])
        self.assertEqual((visit.state, visit.token_no), ('booked', 0), 'no token before arrival')
        self.camp.state = 'running'
        self.api(self.registration).sync(self.camp.id, {'visits': [
            {'client_uuid': v_uuid, 'patient': p_uuid, 'state': 'registered', 'token_no': 7, 'consent_confirmed': True}]})
        self.assertEqual((visit.state, visit.token_no, visit.consent_confirmed), ('registered', 7, True))
        # Not counted as a patient until they come.
        _p, other = self._register('Walk In')
        p2 = self.env['camp.patient'].create({'name': 'No Show', 'sex': 'male', 'age_years': 30, 'consent_care': True})
        self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': p2.id, 'state': 'booked'})
        self.env['camp.team.member'].create({'camp_id': self.camp.id, 'user_id': self.coordinator.id,
                                             'role': 'coordinator'})
        summary = self.api(self.coordinator).camp_summary(self.camp.id)
        self.assertEqual((summary['patients'], summary['pre_registered_not_come']), (2, 1))

    def test_reminders_and_referral_confirmation(self):
        hospital = self.env['res.partner'].create({'name': 'Hope Hospital', 'camp_is_hospital': True})
        patient, visit = self._register('Remind Rubina', phone='0300 1234567', consent_messages=True)
        referral = self.env['camp.referral'].sudo().create({'visit_id': visit.id, 'hospital_id': hospital.id,
                                                            'reason': 'Eye check'})
        self.assertTrue(referral.confirm_code and referral.confirm_url.endswith(referral.confirm_code))
        _q, quiet = self._register('No Messages', phone='0300 7654321')   # did not agree to messages
        self.env['camp.referral'].sudo().create({'visit_id': quiet.id, 'hospital_id': hospital.id, 'reason': 'x'})
        self.env['camp.reminder']._generate(self.camp)
        reminders = self.env['camp.reminder'].search([('camp_id', '=', self.camp.id)])
        self.assertEqual(reminders.patient_id, patient, 'only patients who agreed to messages')
        self.assertIn('Hope Hospital', reminders.message)
        self.env['camp.reminder']._generate(self.camp)
        self.assertEqual(self.env['camp.reminder'].search_count([('camp_id', '=', self.camp.id)]), 1, 'made once')

        # A follow-up volunteer marks it sent from the phone.
        self.env['camp.team.member'].create({'camp_id': self.camp.id, 'user_id': self.coordinator.id,
                                             'role': 'coordinator'})
        feed = self.api(self.coordinator).changes(self.camp.id, since=None)
        self.assertEqual([r['kind'] for r in feed['reminders']], ['referral'])
        self.api(self.coordinator).sync(self.camp.id, {'reminder_sends': [
            {'client_uuid': _uuid(), 'reminder': reminders.client_uuid, 'result': 'sent'}]})
        self.assertEqual(reminders.state, 'sent')

        # The hospital confirms: follow-up call closed.
        followup = self.env['camp.followup'].search([('referral_id', '=', referral.id)])
        referral._confirm_arrival('Reception')
        self.assertEqual((referral.status, referral.received_by), ('attended', 'Reception'))
        self.assertEqual(followup.state, 'closed')

    def test_merge_duplicates(self):
        a = self.env['camp.patient'].create({'name': 'Twin Tariq', 'sex': 'male', 'age_years': 33,
                                             'phone': '0300-1112223', 'consent_care': True, 'allergies': 'Penicillin'})
        b = self.env['camp.patient'].create({'name': 'Tariq', 'sex': 'male', 'age_years': 33, 'phone': '03001112223',
                                             'area': 'Youhanabad', 'consent_care': True, 'allergies': 'sulfa'})
        self.assertIn(a, self.env['camp.patient'].search([('has_duplicate', '=', True)]))
        old = self.env['camp.camp'].create({'name': 'Old', 'state': 'running'})
        vb = self.env['camp.visit'].create({'camp_id': old.id, 'patient_id': b.id})
        wizard = self.env['camp.patient.merge'].with_user(self.coordinator).with_context(
            active_model='camp.patient', active_ids=[a.id, b.id]).create({'keep_id': a.id})
        wizard.action_merge()
        self.assertEqual(vb.patient_id, a)
        self.assertEqual((a.area, a.allergies), ('Youhanabad', 'Penicillin, sulfa'))
        self.assertFalse(b.active)
        self.assertEqual(b.merged_into_id, a)
        # Both at the same camp: refuse.
        c = self.env['camp.patient'].create({'name': 'X', 'sex': 'male', 'age_years': 1, 'consent_care': True})
        d = self.env['camp.patient'].create({'name': 'X', 'sex': 'male', 'age_years': 1, 'consent_care': True})
        for p in (c, d):
            self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': p.id})
        w2 = self.env['camp.patient.merge'].with_context(active_model='camp.patient', active_ids=[c.id, d.id]).create(
            {'keep_id': c.id})
        with self.assertRaises(UserError):
            w2.action_merge()


@tagged('post_install', '-at_install')
class TestReferralPage(HttpCase):

    def test_hospital_confirms_by_link(self):
        camp = self.env['camp.camp'].create({'name': 'Link Camp', 'state': 'running'})
        patient = self.env['camp.patient'].create({'name': 'Link Lubna', 'sex': 'female', 'age_years': 30,
                                                   'consent_care': True})
        visit = self.env['camp.visit'].create({'camp_id': camp.id, 'patient_id': patient.id})
        hospital = self.env['res.partner'].create({'name': 'City Hospital', 'camp_is_hospital': True})
        referral = self.env['camp.referral'].create({'visit_id': visit.id, 'hospital_id': hospital.id, 'reason': 'x'})
        page = self.url_open(f'/camp/referral/{referral.confirm_code}')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Link Lubna', page.text)
        self.assertIn('The patient has arrived', page.text)
        bad = self.url_open('/camp/referral/not-a-real-code-at-all-123456')
        self.assertIn('not valid', bad.text)
