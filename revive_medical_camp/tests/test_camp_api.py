import json
import uuid
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged

from .test_camp_flow import TestCampFlow


def _uuid():
    return str(uuid.uuid4())


@tagged('post_install', '-at_install')
class TestCampSync(TestCampFlow):
    """Offline upload: one phone per station, sent as Camp Mode would."""

    def api(self, user):
        return self.env['camp.api'].with_user(user)

    def test_offline_round_trip_and_idempotent_resend(self):
        block = self.api(self.registration).bootstrap(self.camp.id, reserve_tokens=10)['token_block']
        self.assertEqual(block, {'from': 1, 'to': 10})

        p_uuid, v_uuid = _uuid(), _uuid()
        reg_payload = {
            'patients': [{'client_uuid': p_uuid, 'name': 'Offline Asha', 'sex': 'female',
                          'age_years': 30, 'area': 'Youhanabad', 'consent_care': True}],
            'visits': [{'client_uuid': v_uuid, 'patient': p_uuid, 'token_no': block['from'],
                        'consent_confirmed': True}],
        }
        res = self.api(self.registration).sync(self.camp.id, reg_payload)
        self.assertEqual([r['status'] for r in res['results']['patients']], ['created'])
        self.assertEqual([r['status'] for r in res['results']['visits']], ['created'])
        visit = self.env['camp.visit'].search([('client_uuid', '=', v_uuid)])
        self.assertEqual(visit.token_no, 1)

        # Sending the same batch again (lost reply) creates nothing new.
        again = self.api(self.registration).sync(self.camp.id, reg_payload)
        self.assertEqual([r['status'] for r in again['results']['patients']], ['exists'])
        self.assertEqual([r['status'] for r in again['results']['visits']], ['exists'])
        self.assertEqual(self.env['camp.patient'].search_count([('client_uuid', '=', p_uuid)]), 1)

        # A token registered from the server after the block skips the reserved range.
        _p, server_visit = self._register('Walk-in')
        self.assertEqual(server_visit.token_no, 11)

        # Nurse, doctor and pharmacist phones.
        vit = self.api(self.nurse).sync(self.camp.id, {'vitals': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'bp_systolic': 190, 'bp_diastolic': 115, 'pulse': 90}]})
        self.assertEqual(vit['results']['vitals'][0]['status'], 'created')
        self.assertEqual(visit.priority, 'urgent')

        c_uuid, l_uuid = _uuid(), _uuid()
        doc = self.api(self.doctor).sync(self.camp.id, {
            'consultations': [{'client_uuid': c_uuid, 'visit': v_uuid, 'complaint': 'Dizzy',
                               'diagnosis_codes': ['I10'], 'finished': True}],
            'prescription_lines': [{'client_uuid': l_uuid, 'consultation': c_uuid,
                                    'formulary_id': self.formulary.id, 'days': 3}],
        })
        self.assertEqual(doc['results']['consultations'][0]['status'], 'created')
        self.assertEqual(doc['results']['prescription_lines'][0]['status'], 'created')
        self.assertEqual(visit.state, 'at_pharmacy')
        self.assertEqual(visit.consultation_ids.diagnosis_ids.code, 'I10')

        pharm = self.api(self.pharmacist).sync(self.camp.id, {'dispenses': [
            {'client_uuid': _uuid(), 'line': l_uuid}]})
        self.assertEqual(pharm['results']['dispenses'][0]['status'], 'updated')
        self.assertEqual(visit.state, 'done')
        self.assertFalse(pharm['warnings'])

        # Changes feed shows the work of the other stations.
        feed = self.api(self.registration).changes(self.camp.id, since=None)
        self.assertIn(v_uuid, [v['client_uuid'] for v in feed['visits']])

    def test_prescription_templates(self):
        icd = self.env.ref('revive_medical_camp.icd_i10')
        shared = self.env['camp.rx.template'].create({
            'name': 'High BP', 'user_id': False, 'diagnosis_ids': [(6, 0, icd.ids)],
            'line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'days': 30})]})
        boot = self.api(self.doctor).bootstrap(self.camp.id)
        by_name = {t['name']: t for t in boot['rx_templates']}
        self.assertEqual(by_name['High BP']['diagnosis_codes'], ['I10'])
        # Registration phones do not get templates.
        self.assertEqual(self.api(self.registration).bootstrap(self.camp.id)['rx_templates'], [])

        # A doctor saves their own from the phone (with a medicine to buy outside).
        t_uuid = _uuid()
        res = self.api(self.doctor).sync(self.camp.id, {'rx_templates': [{
            'client_uuid': t_uuid, 'name': 'My cough', 'diagnosis_codes': ['I10'], 'advice': 'Rest',
            'lines': [{'formulary_id': self.formulary.id, 'days': 5},
                      {'outside_medicine': 'Cough syrup', 'days': 3}]}]})
        self.assertEqual(res['results']['rx_templates'][0]['status'], 'created')
        mine = self.env['camp.rx.template'].search([('client_uuid', '=', t_uuid)])
        self.assertEqual(mine.user_id, self.doctor)
        self.assertEqual(len(mine.line_ids), 2)

        # Another doctor does not see it; nobody changes the shared one from a phone.
        other = [t['name'] for t in self.api(self.doctor_no_pmdc).bootstrap(self.camp.id)['rx_templates']]
        self.assertNotIn('My cough', other)
        hack = self.api(self.doctor).sync(self.camp.id, {'rx_templates': [
            {'client_uuid': shared.client_uuid, 'name': 'Changed'}]})
        self.assertEqual(hack['results']['rx_templates'][0]['status'], 'error')
        self.assertEqual(shared.name, 'High BP')

        # Deleting on the phone archives it; the change feed tells the phones.
        since = fields.Datetime.to_string(fields.Datetime.now() - timedelta(minutes=5))
        self.api(self.doctor).sync(self.camp.id, {'rx_templates': [{'client_uuid': t_uuid, 'active': False}]})
        self.assertFalse(mine.active)
        changed = self.api(self.doctor).changes(self.camp.id, since=since)['rx_templates_changed']
        self.assertIn((t_uuid, False), [(t['client_uuid'], t['active']) for t in changed])

    def test_end_of_day_summary(self):
        icd = self.env.ref('revive_medical_camp.icd_i10')
        for name in ['Sum One', 'Sum Two']:
            _p, visit = self._register(name)
            consult = self.env['camp.consultation'].with_user(self.doctor).create({
                'visit_id': visit.id, 'diagnosis_ids': [(6, 0, icd.ids)],
                'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'days': 1, 'quantity': 2})]})
            consult.action_finish()
            consult.prescription_line_ids.with_user(self.pharmacist).action_dispense()
        _p, left = self._register('Sum Left')
        left.action_cancel()

        data = self.env['camp.api'].with_user(self.coordinator).camp_summary(self.camp.id)
        self.assertEqual((data['patients'], data['seen_by_doctor'], data['left_early']), (2, 2, 1))
        self.assertEqual(data['top_diagnoses'][0]['code'], 'I10')
        self.assertEqual(data['top_diagnoses'][0]['count'], 2)
        self.assertEqual(data['medicine_units_given'], 4)
        self.assertEqual(data['top_medicines'][0]['quantity'], 4)
        self.assertNotIn('Sum One', str(data), 'no names in the summary')
        # Station staff cannot pull it; the team list comes with every sync.
        with self.assertRaises(AccessError):
            self.env['camp.api'].with_user(self.nurse).camp_summary(self.camp.id)
        self.assertTrue(self.api(self.nurse).changes(self.camp.id, since=None)['team'])

    def test_call_screen(self):
        _p, visit = self._register('Called Kiran')
        v_uuid = visit.client_uuid
        res = self.api(self.doctor).sync(self.camp.id, {'calls': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'station': 'doctor', 'room': '2',
             'called_at': '2026-10-12 06:00:00'}]})
        self.assertEqual(res['results']['calls'][0]['status'], 'updated')
        self.assertEqual((visit.called_station, visit.called_room), ('doctor', '2'))
        # An older call arriving late does not undo the newer one.
        self.api(self.nurse).sync(self.camp.id, {'calls': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'station': 'triage', 'called_at': '2026-10-12 05:00:00'}]})
        self.assertEqual(visit.called_station, 'doctor')
        # Other phones (the call screen) see it.
        feed = self.api(self.registration).changes(self.camp.id, since=None)
        row = next(v for v in feed['visits'] if v['client_uuid'] == v_uuid)
        self.assertEqual((row['called_station'], row['called_room']), ('doctor', '2'))
        # Only the station's own staff can call to it.
        bad = self.api(self.registration).sync(self.camp.id, {'calls': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'station': 'doctor'}]})
        self.assertEqual(bad['results']['calls'][0]['status'], 'error')

    def test_allergies_and_pregnancy(self):
        self.formulary.write({'allergy_group': 'penicillin', 'pregnancy_risk': 'avoid',
                              'mg_per_unit': 500, 'child_mg_per_kg': 15, 'child_max_mg_per_kg_day': 60})
        p_uuid, v_uuid = _uuid(), _uuid()
        self.api(self.registration).sync(self.camp.id, {
            'patients': [{'client_uuid': p_uuid, 'name': 'Allergic Amna', 'sex': 'female', 'age_years': 25,
                          'consent_care': True, 'allergies': 'Penicillin'}],
            'visits': [{'client_uuid': v_uuid, 'patient': p_uuid, 'consent_confirmed': True, 'pregnant': True}]})
        visit = self.env['camp.visit'].search([('client_uuid', '=', v_uuid)])
        self.assertEqual(visit.patient_id.allergies, 'Penicillin')
        self.assertTrue(visit.pregnant)

        boot = self.api(self.doctor).bootstrap(self.camp.id)
        med = next(f for f in boot['formulary'] if f['id'] == self.formulary.id)
        self.assertEqual((med['allergy_group'], med['pregnancy_risk'], med['child_mg_per_kg']), ('penicillin', 'avoid', 15))
        row = next(p for p in boot['patients'] if p['client_uuid'] == p_uuid)
        self.assertEqual(row['allergies'], 'Penicillin')
        self.assertTrue(next(v for v in boot['visits'] if v['client_uuid'] == v_uuid)['pregnant'])

        # The doctor finds out more during the visit.
        self.api(self.doctor).sync(self.camp.id, {'consultations': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'complaint': 'Rash',
             'patient_allergies': 'Penicillin, sulfa', 'pregnant': False}]})
        self.assertEqual(visit.patient_id.allergies, 'Penicillin, sulfa')
        self.assertFalse(visit.pregnant)

    def test_last_prescription_for_returning_patient(self):
        old_camp = self.env['camp.camp'].create({'name': 'Last Year Camp', 'state': 'running'})
        patient = self.env['camp.patient'].create({'name': 'Returning Ravi', 'sex': 'male', 'age_years': 50,
                                                   'consent_care': True})
        old_visit = self.env['camp.visit'].create({'camp_id': old_camp.id, 'patient_id': patient.id})
        # Last year's doctor (not on this year's team, nor this doctor on last year's).
        consult = self.env['camp.consultation'].create({
            'visit_id': old_visit.id, 'advice': 'Less salt', 'doctor_id': self.doctor_no_pmdc.id,
            'diagnosis_ids': [(6, 0, [self.env.ref('revive_medical_camp.icd_i10').id])],
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'days': 30}),
                                      (0, 0, {'outside_medicine': 'Amlodipine 5 mg', 'days': 30})]})
        consult.state = 'done'
        # Today he comes to this camp.
        self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': patient.id})

        rows = {p['name']: p for p in self.api(self.doctor).bootstrap(self.camp.id)['patients']}
        last = rows['Returning Ravi']['last_rx']
        self.assertEqual(last['camp_name'], 'Last Year Camp')
        self.assertEqual(last['diagnosis_codes'], ['I10'])
        self.assertEqual(last['advice'], 'Less salt')
        self.assertEqual(sorted(line['outside_medicine'] for line in last['lines']), ['', 'Amlodipine 5 mg'])
        # Registration does not see medicines.
        reg = {p['name']: p for p in self.api(self.registration).bootstrap(self.camp.id)['patients']}
        self.assertNotIn('last_rx', reg['Returning Ravi'])

    def test_token_clash_between_two_phones(self):
        a = self.api(self.registration).sync(self.camp.id, {
            'patients': [{'client_uuid': 'pa', 'name': 'A', 'sex': 'male', 'consent_care': True},
                         {'client_uuid': 'pb', 'name': 'B', 'sex': 'male', 'consent_care': True}],
            'visits': [{'client_uuid': 'va', 'patient': 'pa', 'token_no': 7},
                       {'client_uuid': 'vb', 'patient': 'pb', 'token_no': 7}],
        })
        self.assertEqual([r['status'] for r in a['results']['visits']], ['created', 'created'])
        tokens = self.env['camp.visit'].search([('client_uuid', 'in', ['va', 'vb'])]).mapped('token_no')
        self.assertEqual(len(set(tokens)), 2)
        self.assertTrue(any('Token 7' in w['message'] for w in a['warnings']))

    def test_same_patient_registered_on_two_phones(self):
        patient, visit = self._register('Twice')
        res = self.api(self.registration).sync(self.camp.id, {'visits': [
            {'client_uuid': _uuid(), 'patient': patient.id}]})
        self.assertEqual(res['results']['visits'][0]['id'], visit.id)
        self.assertTrue(res['warnings'])

    def test_bad_record_does_not_block_the_batch(self):
        res = self.api(self.registration).sync(self.camp.id, {
            'patients': [{'client_uuid': 'ok1', 'name': 'Fine', 'sex': 'female', 'consent_care': True},
                         {'client_uuid': 'bad1', 'name': 'No sex given'},
                         {'name': 'no uuid', 'sex': 'male'}],
            'visits': [{'client_uuid': 'v-missing', 'patient': 'does-not-exist'},
                       {'client_uuid': 'v-ok', 'patient': 'ok1'}],
        })
        self.assertEqual([r['status'] for r in res['results']['patients']], ['created', 'error', 'error'])
        self.assertEqual([r['status'] for r in res['results']['visits']], ['error', 'created'])

    def test_roles_are_enforced_in_sync(self):
        _p, visit = self._register('Guarded')
        res = self.api(self.registration).sync(self.camp.id, {'consultations': [
            {'client_uuid': _uuid(), 'visit': visit.id, 'complaint': 'x'}]})
        self.assertEqual(res['results']['consultations'][0]['status'], 'error')
        self.assertFalse(visit.sudo().consultation_ids)

    def test_offline_dispense_shortage_is_a_warning(self):
        _p, visit = self._register('Short')
        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': visit.id,
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'quantity': 150})]})
        res = self.api(self.pharmacist).sync(self.camp.id, {'dispenses': [
            {'client_uuid': _uuid(), 'line': consult.prescription_line_ids.id}]})
        self.assertEqual(res['results']['dispenses'][0]['status'], 'updated')
        self.assertTrue(res['warnings'])
        self.assertEqual(consult.prescription_line_ids.shortage_qty, 44)

    def test_bootstrap_per_role(self):
        pharm = self.api(self.pharmacist).bootstrap(self.camp.id)
        stock = {f['id']: f['stock_qty'] for f in pharm['formulary']}
        self.assertEqual(stock[self.formulary.id], 106)   # 6 + 100; expired 50 not counted
        self.assertIsNone(pharm['token_block'])           # pharmacists do not register
        reg = self.api(self.registration).bootstrap(self.camp.id)
        self.assertEqual(reg['consultations'], [])        # no clinical notes for registration
        self.assertTrue(reg['diagnosis_codes'] is not None)
        self.assertIn('server_time', reg)

    def test_close_camp_from_phone(self):
        _p, visit = self._register('Waiting')
        with self.assertRaises(Exception):
            self.api(self.registration).close_camp(self.camp.id)     # not a coordinator
        with self.assertRaises(Exception):
            self.api(self.coordinator).close_camp(self.camp.id)      # a patient is still waiting
        visit.sudo().action_cancel()
        status = self.api(self.coordinator).close_camp(self.camp.id)
        self.assertEqual(status['camp']['state'], 'closed')

    def test_followups_created_and_called(self):
        _p, visit = self._register('Follow Me')
        hospital = self.env['res.partner'].create({'name': 'FU Hospital', 'camp_is_hospital': True})
        referral = self.env['camp.referral'].with_user(self.doctor).create({
            'visit_id': visit.id, 'hospital_id': hospital.id, 'reason': 'Eye', 'urgency': 'urgent'})
        fu = self.env['camp.followup'].search([('visit_id', '=', visit.id), ('kind', '=', 'referral')])
        self.assertEqual(len(fu), 1)
        self.assertEqual(fu.due_date, fields.Date.today() + timedelta(days=1))

        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': visit.id, 'follow_up_needed': True, 'follow_up_reason': 'Check sugar'})
        consult.with_user(self.doctor).action_finish()
        self.assertTrue(self.env['camp.followup'].search([('visit_id', '=', visit.id), ('kind', '=', 'doctor')]))

        followup_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Caller', 'login': 'camp_caller',
            'group_ids': [(6, 0, [self.env.ref('revive_medical_camp.group_camp_followup').id])]})
        self.env['camp.team.member'].create({'camp_id': self.camp.id, 'user_id': followup_user.id, 'role': 'followup'})
        boot = self.api(followup_user).bootstrap(self.camp.id)
        self.assertEqual(len(boot['followups']), 2)
        self.assertEqual(boot['consultations'], [])   # callers never see clinical notes
        res = self.api(followup_user).sync(self.camp.id, {'followup_calls': [
            {'client_uuid': _uuid(), 'followup': fu.id, 'result': 'reached',
             'notes': 'Went yesterday', 'outcome': 'Surgery booked', 'referral_attended': True}]})
        self.assertEqual(res['results']['followup_calls'][0]['status'], 'updated')
        self.assertEqual(fu.state, 'reached')
        self.assertEqual(fu.call_count, 1)
        self.assertEqual(referral.status, 'attended')

    def test_urgent_without_referral_gets_followup(self):
        _p, visit = self._register('Urgent Only')
        self.env['camp.vitals'].with_user(self.nurse).create({'visit_id': visit.id, 'bp_systolic': 200})
        visit.sudo().action_done()
        self.assertTrue(self.env['camp.followup'].search([('visit_id', '=', visit.id), ('kind', '=', 'red_flag')]))

    def test_stock_count(self):
        res = self.api(self.pharmacist).sync(self.camp.id, {'stock_counts': [
            {'client_uuid': 'count-1', 'lines': [{'formulary_id': self.formulary.id, 'counted_qty': 140}]}]})
        self.assertEqual(res['results']['stock_counts'][0]['status'], 'created')
        count = self.env['camp.stock.count'].search([('client_uuid', '=', 'count-1')])
        self.assertEqual(count.line_ids.expected_qty, 156)   # 6 + 100 + 50 expired, all batches
        self.assertEqual(count.line_ids.difference, -16)
        again = self.api(self.pharmacist).sync(self.camp.id, {'stock_counts': [{'client_uuid': 'count-1', 'lines': []}]})
        self.assertEqual(again['results']['stock_counts'][0]['status'], 'exists')
        denied = self.api(self.registration).sync(self.camp.id, {'stock_counts': [
            {'client_uuid': 'count-2', 'lines': []}]})
        self.assertEqual(denied['results']['stock_counts'][0]['status'], 'error')
        html = self.env['ir.actions.report']._render_qweb_html(
            'revive_medical_camp.action_report_camp_summary', self.camp.ids)[0]
        self.assertIn(b'Stock check', html)

    def test_returning_patients_by_area_and_recent(self):
        self.camp.area = 'Youhanabad, Lahore'
        Patient = self.env['camp.patient']
        near = Patient.create({'name': 'Near', 'sex': 'male', 'area': 'youhanabad'})
        far = Patient.create({'name': 'Far', 'sex': 'male', 'area': 'Karachi'})
        old = Patient.create({'name': 'Old', 'sex': 'male', 'area': 'Youhanabad'})
        self.env.cr.execute("UPDATE camp_patient SET create_date = now() - interval '3 years' WHERE id = %s", (old.id,))
        self.env.invalidate_all()
        ids = [p['id'] for p in self.api(self.registration).bootstrap(self.camp.id)['patients']]
        self.assertIn(near.id, ids)
        self.assertNotIn(far.id, ids)
        self.assertNotIn(old.id, ids)

    def test_closed_camp_stays_for_followup(self):
        self.camp.sudo().state = 'closed'
        coord_camps = [c['id'] for c in self.api(self.coordinator).me()['camps']]
        self.assertIn(self.camp.id, coord_camps)
        reg_camps = [c['id'] for c in self.api(self.registration).me()['camps']]
        self.assertNotIn(self.camp.id, reg_camps)

    def test_outsider_cannot_bootstrap_other_camp(self):
        with self.assertRaises(Exception):
            self.api(self.outsider_reg).bootstrap(self.camp.id)


@tagged('post_install', '-at_install')
class TestCampApiHttp(HttpCase):
    """Sign in, use the key, sign out — over real HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Camp Phone', 'login': 'camp_phone', 'password': 'camp_phone_pw_123',
            'group_ids': [(6, 0, [cls.env.ref('revive_medical_camp.group_camp_registration').id])],
        })
        cls.plain = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Plain Staff', 'login': 'plain_staff', 'password': 'plain_staff_pw_123',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.camp = cls.env['camp.camp'].create({'name': 'HTTP Camp', 'state': 'running'})
        cls.env['camp.team.member'].create({'camp_id': cls.camp.id, 'user_id': cls.user.id, 'role': 'registration'})

    def call(self, method, path, body=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        if method == 'GET':
            resp = self.url_open(path, headers=headers)
        else:
            resp = self.url_open(path, data=json.dumps(body or {}), headers=headers)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            self.fail(f'{path} returned {resp.status_code}, not JSON: {resp.text[:300]}')

    def test_login_bootstrap_sync_logout(self):
        status, data = self.call('POST', '/api/camp/login',
                                 {'login': 'camp_phone', 'password': 'wrong', 'device_name': 'Test'})
        self.assertEqual(status, 401)

        status, data = self.call('POST', '/api/camp/login',
                                 {'login': 'plain_staff', 'password': 'plain_staff_pw_123'})
        self.assertEqual(status, 403)      # no camp role -> no key

        status, data = self.call('POST', '/api/camp/login',
                                 {'login': 'camp_phone', 'password': 'camp_phone_pw_123', 'device_name': 'Test'})
        self.assertEqual(status, 200, data)
        token = data['token']
        self.assertIn('registration', data['user']['roles'])
        self.assertIn(self.camp.id, [c['id'] for c in data['camps']])

        status, _ = self.call('GET', '/api/camp/me')
        self.assertEqual(status, 401)      # no key

        status, boot = self.call('GET', f'/api/camp/{self.camp.id}/bootstrap?reserve_tokens=5', token=token)
        self.assertEqual(status, 200, boot)
        self.assertEqual(boot['token_block']['to'] - boot['token_block']['from'], 4)

        status, res = self.call('POST', f'/api/camp/{self.camp.id}/sync', {
            'patients': [{'client_uuid': 'http-p', 'name': 'Via HTTP', 'sex': 'male', 'consent_care': True}],
            'visits': [{'client_uuid': 'http-v', 'patient': 'http-p', 'token_no': boot['token_block']['from']}],
        }, token=token)
        self.assertEqual(status, 200, res)
        self.assertEqual(res['results']['visits'][0]['status'], 'created')

        status, q = self.call('GET', f'/api/camp/{self.camp.id}/queue/registration', token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(q['visits']), 1)

        status, err = self.call('GET', '/api/camp/999999/bootstrap', token=token)
        self.assertEqual(status, 404)

        # The camp key does not work for normal JSON-RPC.
        resp = self.url_open('/json/2/res.partner/search', data=json.dumps({'domain': []}),
                             headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'})
        self.assertNotEqual(resp.status_code, 200)

        status, _ = self.call('POST', '/api/camp/logout', token=token)
        self.assertEqual(status, 200)
        status, _ = self.call('GET', '/api/camp/me', token=token)
        self.assertEqual(status, 401)      # key deleted

    def test_expired_key_is_refused(self):
        key = self.env['res.users.apikeys'].with_user(self.user).sudo()._generate(
            'revive_camp', 'old phone', fields.Datetime.now() + timedelta(days=1))
        self.env['res.users.apikeys'].sudo().search([('user_id', '=', self.user.id)]).write(
            {'expiration_date': fields.Datetime.now() - timedelta(days=1)})
        status, _ = self.call('GET', '/api/camp/me', token=key)
        self.assertEqual(status, 401)


@tagged('post_install', '-at_install')
class TestCampDiagnosesAndOutside(TestCampFlow):

    def api(self, user):
        return self.env['camp.api'].with_user(user)

    def test_full_icd10_list_is_loaded(self):
        Code = self.env['camp.diagnosis.code']
        self.assertGreater(Code.search_count([('source', '=', 'icd10')]), 10000)
        self.assertEqual(Code.search_count([('code', '=', 'I10')]), 1)          # no duplicate of the camp list
        self.assertEqual(Code.search([('code', '=', 'I10')]).source, 'camp')    # keeps its Urdu name
        self.assertTrue(Code.search([('code', '=', 'A00.0')]))                  # from the ICD-10 file

    def test_full_list_only_for_doctors_and_pharmacists(self):
        doctor = self.api(self.doctor).bootstrap(self.camp.id)['diagnosis_codes']
        reg = self.api(self.registration).bootstrap(self.camp.id)['diagnosis_codes']
        self.assertGreater(len(doctor), 10000)
        self.assertLess(len(reg), 1000)

    def test_doctor_adds_a_diagnosis_from_the_phone(self):
        _p, visit = self._register('New Dx')
        res = self.api(self.doctor).sync(self.camp.id, {
            'diagnosis_codes': [{'client_uuid': _uuid(), 'code': 'cust-ab12', 'name': 'Snake-bite anxiety'}],
            'consultations': [{'client_uuid': _uuid(), 'visit': visit.id, 'diagnosis_codes': ['CUST-AB12']}],
        })
        self.assertEqual(res['results']['diagnosis_codes'][0]['status'], 'created')
        code = self.env['camp.diagnosis.code'].search([('code', '=', 'CUST-AB12')])
        self.assertEqual(code.source, 'custom')
        self.assertEqual(visit.consultation_ids.diagnosis_ids, code)
        # Other phones get it with their next sync.
        changed = self.api(self.doctor).changes(self.camp.id, since='2000-01-01 00:00:00')['diagnosis_codes_changed']
        self.assertIn('CUST-AB12', [c['code'] for c in changed])
        # Registration staff cannot add diagnoses.
        bad = self.api(self.registration).sync(self.camp.id, {'diagnosis_codes': [
            {'client_uuid': _uuid(), 'code': 'X1', 'name': 'x'}]})
        self.assertEqual(bad['results']['diagnosis_codes'][0]['status'], 'error')

    def test_buy_outside_medicine(self):
        _p, visit = self._register('Outside')
        res = self.api(self.doctor).sync(self.camp.id, {
            'consultations': [{'client_uuid': 'c-out', 'visit': visit.id, 'complaint': 'x', 'finished': True}],
            'prescription_lines': [{'client_uuid': 'l-out', 'consultation': 'c-out',
                                    'outside_medicine': 'Insulin glargine 100 IU/ml', 'days': 30, 'quantity': 1}],
        })
        self.assertFalse([r for k in res['results'].values() for r in k if r['status'] == 'error'], res)
        line = visit.prescription_line_ids
        self.assertEqual(line.state, 'outside')
        self.assertEqual(visit.state, 'done')      # nothing to give at the pharmacy
        html = self.env['ir.actions.report']._render_qweb_html(
            'revive_medical_camp.action_report_prescription_slip', visit.consultation_ids.ids)[0]
        self.assertIn(b'Insulin glargine', html)
        self.assertIn(b'Buy from a pharmacy', html)
        # A line needs either a camp medicine or an outside name.
        bad = self.api(self.doctor).sync(self.camp.id, {'prescription_lines': [
            {'client_uuid': 'l-bad', 'consultation': 'c-out', 'days': 3}]})
        self.assertEqual(bad['results']['prescription_lines'][0]['status'], 'error')
