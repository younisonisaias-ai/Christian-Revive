import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged

from .test_camp_flow import TestCampFlow


@tagged('post_install', '-at_install')
class TestCampSecurityHttp(HttpCase):
    """Sign-in lockout with CAPTCHA, first sign-in password change,
    remote sign-out of a lost phone, referral link limits."""

    def setUp(self):
        super().setUp()
        self.camp = self.env['camp.camp'].create({'name': 'Secure Camp', 'state': 'running'})
        self.member = self.env['camp.team.member'].create({
            'camp_id': self.camp.id, 'name': 'Safe Sana', 'role': 'registration', 'phone': '03009998887'})
        action = self.member.action_create_login()
        self.password = action['params']['message'].split('Password: ')[1].split()[0]
        self.login = self.member.user_id.login

    def post(self, path, body, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        res = self.url_open(path, data=json.dumps(body), headers=headers)
        return res.status_code, res.json()

    def get(self, path, token):
        res = self.url_open(path, headers={'Authorization': f'Bearer {token}'})
        return res.status_code, res.json()

    def test_lockout_and_captcha(self):
        for _i in range(3):
            code, body = self.post('/api/camp/login', {'login': self.login, 'password': 'wrong'})
            self.assertEqual((code, body['error']['code']), (401, 'unauthorized'))
        # 4th try: a CAPTCHA picture, even with the right password.
        code, body = self.post('/api/camp/login', {'login': self.login, 'password': self.password})
        self.assertEqual(body['error']['code'], 'captcha_required')
        self.assertTrue(body['error']['captcha_image'].startswith('iVBOR'), 'a PNG picture')
        # The wrong answer gives a fresh picture.
        code, body2 = self.post('/api/camp/login', {'login': self.login, 'password': self.password,
                                                    'captcha_token': body['error']['captcha_token'],
                                                    'captcha_answer': '00000'})
        self.assertEqual(body2['error']['code'], 'captcha_required')
        self.assertNotEqual(body2['error']['captcha_token'], body['error']['captcha_token'])
        # The right answer (read from the server for the test) lets the person in.
        captcha = self.env['camp.captcha'].sudo().search([('token', '=', body2['error']['captcha_token'])])
        answer = next(a for a in (f'{n:05d}' for n in range(22222, 100000))
                      if captcha._hash(captcha.token, a) == captcha.answer_hash)
        code, ok = self.post('/api/camp/login', {'login': self.login, 'password': self.password,
                                                 'captcha_token': captcha.token, 'captcha_answer': answer})
        self.assertEqual(code, 200)
        self.assertTrue(ok['token'])
        self.assertTrue(ok['user']['must_change_password'], 'new logins choose their own password')
        self.assertTrue(self.env['camp.audit.log'].search([('action', '=', 'sign_in_failed')]))

    def test_locked_after_ten_failures(self):
        Throttle = self.env['camp.auth.throttle']
        keys = [f'login:{self.login.lower()}', 'ip:test']
        for _i in range(10):
            Throttle.failed(keys, lock_key=keys[0])
        code, body = self.post('/api/camp/login', {'login': self.login, 'password': self.password})
        self.assertEqual((code, body['error']['code']), (429, 'locked'))

    def test_first_sign_in_password_change_and_remote_wipe(self):
        code, data = self.post('/api/camp/login', {'login': self.login, 'password': self.password})
        token = data['token']
        code, body = self.get(f'/api/camp/{self.camp.id}/bootstrap', token)
        self.assertEqual((code, body['error']['code']), (403, 'password_change_required'))
        code, body = self.post('/api/camp/password', {'old_password': self.password, 'new_password': 'short'}, token)
        self.assertEqual(code, 400)
        code, body = self.post('/api/camp/password', {'old_password': self.password, 'new_password': 'NewPass2026'},
                               token)
        self.assertEqual(code, 200)
        code, body = self.get(f'/api/camp/{self.camp.id}/bootstrap', token)
        self.assertEqual(code, 200)
        self.assertTrue(self.env['camp.audit.log'].search([('action', '=', 'download'), ('camp_id', '=', self.camp.id)]))

        # Lost phone: the coordinator signs it out; the phone is told to wipe.
        self.member.action_sign_out_phone()
        code, body = self.get(f'/api/camp/{self.camp.id}/changes', token)
        self.assertEqual((code, body['error']['code']), (401, 'wiped'))
        # A key that simply expired is not a wipe.
        code, body = self.get(f'/api/camp/{self.camp.id}/changes', 'x' * 40)
        self.assertEqual(body['error']['code'], 'unauthorized')

    def test_referral_link_limits(self):
        patient = self.env['camp.patient'].create({'name': 'Ref Rani', 'sex': 'female', 'age_years': 40,
                                                   'consent_care': True})
        visit = self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': patient.id})
        hospital = self.env['res.partner'].create({'name': 'Link Hospital', 'camp_is_hospital': True})
        referral = self.env['camp.referral'].create({'visit_id': visit.id, 'hospital_id': hospital.id, 'reason': 'x'})
        page = self.url_open(f'/camp/referral/{referral.confirm_code}')
        self.assertIn('Ref Rani', page.text)
        self.assertEqual(page.headers.get('X-Robots-Tag'), 'noindex, nofollow')
        # Old link: no patient details.
        self.env.cr.execute('UPDATE camp_referral SET create_date = %s WHERE id = %s',
                            (fields.Datetime.now() - timedelta(days=31), referral.id))
        referral.invalidate_recordset()
        page = self.url_open(f'/camp/referral/{referral.confirm_code}')
        self.assertIn('expired', page.text)
        self.assertNotIn('Ref Rani', page.text)
        # Guessing codes is limited per network address.
        for i in range(21):
            self.url_open(f'/camp/referral/guess-{i:030d}')
        page = self.url_open(f'/camp/referral/guess-{99:030d}')
        self.assertEqual(page.status_code, 429)


@tagged('post_install', '-at_install')
class TestCampAuditRetention(TestCampFlow):

    def test_audit_and_anonymise(self):
        patient, visit = self._register('Private Parveen', phone='03001231231', allergies='sulfa')
        self.env['camp.audit.log'].search([]).unlink()
        patient.with_user(self.registration).write({'area': 'Youhanabad'})
        log = self.env['camp.audit.log'].search([('action', '=', 'change'), ('patient_id', '=', patient.id)])
        self.assertEqual((log.user_id, log.details), (self.registration, 'area'))
        patient.with_user(self.registration).web_read({'name': {}})
        self.assertTrue(self.env['camp.audit.log'].search([('action', '=', 'view'), ('patient_id', '=', patient.id)]))
        self.env['camp.patient'].browse(patient.id).export_data(['name'])   # admin: registration staff cannot export
        self.assertTrue(self.env['camp.audit.log'].search([('action', '=', 'export'), ('patient_id', '=', patient.id)]))

        # Retention: nothing happens while the setting is 0.
        self.env['camp.patient']._cron_retention()
        self.assertFalse(patient.anonymised)
        self.env['ir.config_parameter'].sudo().set_param('revive_medical_camp.retention_years', 2)
        self.env.cr.execute('UPDATE camp_patient SET create_date = %s WHERE id = %s',
                            (fields.Datetime.now() - timedelta(days=800), patient.id))
        self.env.cr.execute('UPDATE camp_visit SET arrived_at = %s, create_date = %s WHERE id = %s',
                            (fields.Datetime.now() - timedelta(days=800), fields.Datetime.now() - timedelta(days=800),
                             visit.id))
        self.env.invalidate_all()
        self.env['camp.patient']._cron_retention()
        self.assertTrue(patient.anonymised)
        self.assertFalse(patient.phone or patient.allergies)
        self.assertNotIn('Parveen', patient.name)
        self.assertEqual((patient.sex, patient.age_years), ('female', 34), 'kept for anonymous reports')
        self.assertTrue(self.env['camp.audit.log'].search([('action', '=', 'delete'), ('patient_id', '=', patient.id)]))
