import json
import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged

from .test_camp_flow import TestCampFlow


def _uuid():
    return str(uuid.uuid4())


@tagged('post_install', '-at_install')
class TestCampPortalWorkers(TestCampFlow):
    """Station workers as free portal users: rights come only from their team role."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref('base.group_portal')
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        def portal_user(login, role, camp=None, pmdc=None):
            user = Users.create({'name': login.title(), 'login': login, 'password': f'{login}_pw_123',
                                 'group_ids': [(6, 0, [portal.id])]})
            member = cls.env['camp.team.member'].create({'camp_id': (camp or cls.camp).id, 'user_id': user.id, 'role': role})
            if pmdc:
                member.pmdc_number = pmdc
            return user

        cls.p_reg = portal_user('p_reg', 'registration')
        cls.p_nurse = portal_user('p_nurse', 'nurse')
        cls.p_doc = portal_user('p_doc', 'doctor', pmdc='55555-P')
        cls.p_doc_nopmdc = portal_user('p_doc2', 'doctor')
        cls.p_pharm = portal_user('p_pharm', 'pharmacist')
        cls.p_caller = portal_user('p_caller', 'followup')
        cls.other_camp = cls.env['camp.camp'].create({'name': 'Other Camp', 'state': 'running'})
        cls.p_other = portal_user('p_other', 'registration', camp=cls.other_camp)
        cls.p_nobody = Users.create({'name': 'Nobody', 'login': 'p_nobody', 'group_ids': [(6, 0, [portal.id])]})

    def api(self, user):
        return self.env['camp.api'].with_user(user)

    def test_portal_users_are_free_and_have_no_direct_access(self):
        for user in (self.p_reg, self.p_doc, self.p_pharm):
            self.assertTrue(user.share)                  # portal = not a paid internal user
            self.assertFalse(user.has_group('base.group_user'))
        with self.assertRaises(AccessError):
            self.env['camp.patient'].with_user(self.p_reg).search([])
        self.assertEqual(self.p_doc.camp_pmdc_number, '55555-P')

    def test_full_journey_by_portal_workers(self):
        p_uuid, v_uuid, c_uuid, l_uuid = _uuid(), _uuid(), _uuid(), _uuid()
        res = self.api(self.p_reg).sync(self.camp.id, {
            'patients': [{'client_uuid': p_uuid, 'name': 'Portal Patient', 'sex': 'female', 'age_years': 50, 'consent_care': True}],
            'visits': [{'client_uuid': v_uuid, 'patient': p_uuid, 'consent_confirmed': True}]})
        self.assertEqual([r['status'] for r in res['results']['visits']], ['created'])
        visit = self.env['camp.visit'].search([('client_uuid', '=', v_uuid)])
        self.assertEqual(visit.create_uid, self.p_reg)

        res = self.api(self.p_nurse).sync(self.camp.id, {'vitals': [
            {'client_uuid': _uuid(), 'visit': v_uuid, 'bp_systolic': 190}]})
        self.assertEqual(res['results']['vitals'][0]['status'], 'created')
        self.assertEqual(visit.priority, 'urgent')

        hospital = self.env['res.partner'].create({'name': 'Portal Hospital', 'camp_is_hospital': True})
        res = self.api(self.p_doc).sync(self.camp.id, {
            'consultations': [{'client_uuid': c_uuid, 'visit': v_uuid, 'complaint': 'Dizzy',
                               'diagnosis_codes': ['I10'], 'finished': True}],
            'prescription_lines': [{'client_uuid': l_uuid, 'consultation': c_uuid, 'formulary_id': self.formulary.id}],
            'referrals': [{'client_uuid': _uuid(), 'consultation': c_uuid, 'hospital_id': hospital.id, 'reason': 'BP'}]})
        self.assertFalse([r for k in res['results'].values() for r in k if r['status'] == 'error'], res)
        consult = visit.consultation_ids
        self.assertEqual(consult.doctor_id, self.p_doc)
        self.assertEqual(visit.state, 'at_pharmacy')

        res = self.api(self.p_pharm).sync(self.camp.id, {'dispenses': [{'client_uuid': _uuid(), 'line': l_uuid}]})
        self.assertEqual(res['results']['dispenses'][0]['status'], 'updated')
        self.assertEqual(visit.state, 'referred')
        self.assertEqual(consult.prescription_line_ids.dispensed_by_id, self.p_pharm)

        followup = self.env['camp.followup'].search([('visit_id', '=', visit.id), ('kind', '=', 'referral')])
        res = self.api(self.p_caller).sync(self.camp.id, {'followup_calls': [
            {'client_uuid': _uuid(), 'followup': followup.id, 'result': 'reached'}]})
        self.assertEqual(res['results']['followup_calls'][0]['status'], 'updated')
        self.assertEqual(followup.state, 'reached')

    def test_each_role_is_limited(self):
        _p, visit = self._register('Limited')
        # Registration cannot record vitals or consultations.
        res = self.api(self.p_reg).sync(self.camp.id, {
            'vitals': [{'client_uuid': _uuid(), 'visit': visit.id, 'pulse': 80}],
            'consultations': [{'client_uuid': _uuid(), 'visit': visit.id}]})
        self.assertEqual(res['results']['vitals'][0]['status'], 'error')
        self.assertEqual(res['results']['consultations'][0]['status'], 'error')
        # Pharmacist cannot register patients; follow-up cannot dispense.
        res = self.api(self.p_pharm).sync(self.camp.id, {'patients': [
            {'client_uuid': _uuid(), 'name': 'X', 'sex': 'male', 'consent_care': True}]})
        self.assertEqual(res['results']['patients'][0]['status'], 'error')
        # A doctor without a PMDC number cannot save a consultation.
        res = self.api(self.p_doc_nopmdc).sync(self.camp.id, {'consultations': [
            {'client_uuid': _uuid(), 'visit': visit.id}]})
        self.assertEqual(res['results']['consultations'][0]['status'], 'error')
        self.assertIn('PMDC', res['results']['consultations'][0]['error'])
        # Portal coordinators-in-name cannot close the camp.
        with self.assertRaises(AccessError):
            self.api(self.p_reg).close_camp(self.camp.id)

    def test_what_each_role_downloads(self):
        _p, visit = self._register('Downloads')
        self.env['camp.vitals'].create({'visit_id': visit.id, 'pulse': 70})
        self.env['camp.consultation'].create({'visit_id': visit.id, 'complaint': 'secret note'})
        reg = self.api(self.p_reg).bootstrap(self.camp.id)
        self.assertEqual(reg['vitals'], [])
        self.assertEqual(reg['consultations'], [])
        self.assertTrue(reg['patients'])
        nurse = self.api(self.p_nurse).bootstrap(self.camp.id)
        self.assertTrue(nurse['vitals'])
        self.assertEqual(nurse['consultations'], [])
        doc = self.api(self.p_doc).bootstrap(self.camp.id)
        self.assertEqual(doc['consultations'][0]['complaint'], 'secret note')
        caller = self.api(self.p_caller).bootstrap(self.camp.id)
        self.assertEqual(caller['consultations'], [])
        self.assertEqual(caller['vitals'], [])

    def test_other_camps_are_off_limits(self):
        with self.assertRaises(AccessError):
            self.api(self.p_other).bootstrap(self.camp.id)          # not on this camp's team
        self.assertNotIn(self.camp.id, [c['id'] for c in self.api(self.p_other).me()['camps']])
        # A worker of this camp cannot touch another camp's visit, even by id.
        other_patient = self.env['camp.patient'].create({'name': 'Elsewhere', 'sex': 'male', 'consent_care': True})
        other_visit = self.env['camp.visit'].create({'camp_id': self.other_camp.id, 'patient_id': other_patient.id})
        res = self.api(self.p_nurse).sync(self.camp.id, {'vitals': [
            {'client_uuid': _uuid(), 'visit': other_visit.id, 'pulse': 90}]})
        self.assertEqual(res['results']['vitals'][0]['status'], 'error')
        self.assertFalse(other_visit.vitals_ids)
        # A portal user on no team is not a camp worker at all.
        self.assertFalse(self.env['camp.api'].with_user(self.p_nobody)._is_camp_worker())

    def test_coordinator_creates_portal_login(self):
        member = self.env['camp.team.member'].create({
            'camp_id': self.camp.id, 'name': 'New Volunteer', 'phone': '0300 1234567', 'role': 'registration'})
        with self.assertRaises(AccessError):
            member.with_user(self.registration).action_create_login()
        result = member.with_user(self.coordinator).action_create_login()
        self.assertTrue(member.user_id.share)
        self.assertEqual(member.user_id.login, '03001234567')
        self.assertEqual(member.login_type, 'portal')
        self.assertIn('Password', result['params']['message'])
        with self.assertRaises(UserError):
            member.with_user(self.coordinator).action_create_login()
        self.assertIn('registration', self.env['camp.api'].with_user(member.user_id)._roles())


@tagged('post_install', '-at_install')
class TestCampPortalHttp(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        portal = cls.env.ref('base.group_portal')
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.camp = cls.env['camp.camp'].create({'name': 'Portal HTTP Camp', 'state': 'running'})
        cls.worker = Users.create({'name': 'Desk', 'login': 'portal_desk', 'password': 'portal_desk_pw_1',
                                   'group_ids': [(6, 0, [portal.id])]})
        cls.env['camp.team.member'].create({'camp_id': cls.camp.id, 'user_id': cls.worker.id, 'role': 'registration'})
        Users.create({'name': 'Website user', 'login': 'portal_web', 'password': 'portal_web_pw_1',
                      'group_ids': [(6, 0, [portal.id])]})

    def call(self, path, body=None, token=None, get=False):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        resp = self.url_open(path, headers=headers) if get else \
            self.url_open(path, data=json.dumps(body or {}), headers=headers)
        return resp.status_code, resp.json()

    def test_portal_worker_signs_in(self):
        status, _ = self.call('/api/camp/login', {'login': 'portal_web', 'password': 'portal_web_pw_1'})
        self.assertEqual(status, 403)          # an ordinary website customer is not a camp worker
        status, data = self.call('/api/camp/login', {'login': 'portal_desk', 'password': 'portal_desk_pw_1'})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['user']['roles'], ['registration'])
        self.assertEqual([c['id'] for c in data['camps']], [self.camp.id])
        status, boot = self.call(f'/api/camp/{self.camp.id}/bootstrap?reserve_tokens=5', token=data['token'], get=True)
        self.assertEqual(status, 200, boot)
        self.assertIsNotNone(boot['token_block'])
        status, res = self.call(f'/api/camp/{self.camp.id}/sync', {
            'patients': [{'client_uuid': 'pp1', 'name': 'Via portal', 'sex': 'male', 'consent_care': True}],
            'visits': [{'client_uuid': 'pv1', 'patient': 'pp1'}]}, token=data['token'])
        self.assertEqual(status, 200, res)
        self.assertEqual(res['results']['visits'][0]['status'], 'created')
