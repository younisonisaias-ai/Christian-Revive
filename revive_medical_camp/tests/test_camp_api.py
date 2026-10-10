import json
import uuid
from datetime import timedelta

from odoo import fields
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
