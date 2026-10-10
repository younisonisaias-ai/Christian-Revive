from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCampFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Users = env['res.users'].with_context(no_reset_password=True)

        def user(login, *groups, **extra):
            return Users.create({
                'name': login.title(), 'login': login,
                'group_ids': [(6, 0, [env.ref(g).id for g in groups])], **extra,
            })

        cls.registration = user('camp_reg', 'revive_medical_camp.group_camp_registration')
        cls.nurse = user('camp_nurse', 'revive_medical_camp.group_camp_nurse')
        cls.doctor = user('camp_doc', 'revive_medical_camp.group_camp_doctor', camp_pmdc_number='12345-P')
        cls.doctor_no_pmdc = user('camp_doc2', 'revive_medical_camp.group_camp_doctor')
        cls.pharmacist = user('camp_pharm', 'revive_medical_camp.group_camp_pharmacist')
        cls.coordinator = user('camp_coord', 'revive_medical_camp.group_camp_coordinator')
        cls.outsider_reg = user('camp_reg_other', 'revive_medical_camp.group_camp_registration')
        cls.ministry = user('pastor_like', 'base.group_user')

        cls.medicine = env['product.product'].create({
            'name': 'Test Paracetamol', 'type': 'consu', 'is_storable': True,
            'tracking': 'lot', 'use_expiration_date': True,
        })
        cls.formulary = env['camp.formulary'].create({
            'product_id': cls.medicine.id, 'strength': '500 mg',
            'default_dose_template_id': env.ref('revive_medical_camp.dose_1_0_1').id, 'default_days': 5,
        })
        cls.camp = env['camp.camp'].create({'name': 'Test Camp', 'state': 'running'})
        for u, role in [(cls.registration, 'registration'), (cls.nurse, 'nurse'), (cls.doctor, 'doctor'),
                        (cls.doctor_no_pmdc, 'doctor'), (cls.pharmacist, 'pharmacist')]:
            env['camp.team.member'].create({'camp_id': cls.camp.id, 'user_id': u.id, 'role': role})

        # Stock: one expired lot (must never be used) and two good lots.
        now = fields.Datetime.now()
        Lot = env['stock.lot']
        cls.lot_expired = Lot.create({'name': 'EXPIRED', 'product_id': cls.medicine.id,
                                      'expiration_date': now - timedelta(days=10)})
        cls.lot_soon = Lot.create({'name': 'SOON', 'product_id': cls.medicine.id,
                                   'expiration_date': now + timedelta(days=30)})
        cls.lot_later = Lot.create({'name': 'LATER', 'product_id': cls.medicine.id,
                                    'expiration_date': now + timedelta(days=300)})
        Quant = env['stock.quant']
        for lot, qty in [(cls.lot_expired, 50), (cls.lot_soon, 6), (cls.lot_later, 100)]:
            Quant._update_available_quantity(cls.medicine, cls.camp.stock_location_id, qty, lot_id=lot)

    def _register(self, name='Asha', **patient_vals):
        patient = self.env['camp.patient'].with_user(self.registration).create({
            'name': name, 'sex': 'female', 'age_years': 34, 'consent_care': True, **patient_vals})
        visit = self.env['camp.visit'].with_user(self.registration).create({
            'camp_id': self.camp.id, 'patient_id': patient.id})
        return patient, visit

    def test_camp_creates_stock_location(self):
        self.assertTrue(self.camp.stock_location_id)
        self.assertEqual(self.camp.stock_location_id.usage, 'internal')

    def test_full_patient_journey(self):
        patient, visit = self._register()
        self.assertEqual(visit.token_no, 1)
        self.assertTrue(visit.qr_code.startswith('CAMP1:'))
        self.assertTrue(patient.patient_code.startswith('CMP-'))

        # Triage: high BP raises a red flag and moves the patient up the queue.
        self.env['camp.vitals'].with_user(self.nurse).create({
            'visit_id': visit.id, 'bp_systolic': 185, 'bp_diastolic': 100,
            'weight': 60, 'height': 160})
        self.assertEqual(visit.state, 'triaged')
        self.assertEqual(visit.priority, 'urgent')
        self.assertIn(self.env.ref('revive_medical_camp.flag_bp_sys_urgent'), visit.flag_rule_ids)
        self.assertAlmostEqual(visit.vitals_ids.bmi, 23.4, places=1)

        # Doctor: diagnosis + prescription from formulary.
        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': visit.id, 'complaint': 'Headache',
            'diagnosis_ids': [(6, 0, [self.env.ref('revive_medical_camp.icd_i10').id])],
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id})],
        })
        line = consult.prescription_line_ids
        self.assertEqual(line.quantity, 10)  # 1+0+1 x 5 days
        self.assertEqual(visit.state, 'with_doctor')
        consult.with_user(self.doctor).action_finish()
        self.assertEqual(visit.state, 'at_pharmacy')

        # Pharmacy: nearest expiry first, expired lot skipped.
        line.with_user(self.pharmacist).action_dispense()
        self.assertEqual(line.state, 'dispensed')
        self.assertEqual(line.dispensed_qty, 10)
        self.assertEqual(set(line.lot_ids.mapped('name')), {'SOON', 'LATER'})
        self.assertEqual(self.lot_soon.product_qty, 0)
        self.assertEqual(self.lot_later.product_qty, 96)
        self.assertEqual(self.lot_expired.product_qty, 50)
        self.assertEqual(line.move_ids.state, 'done')
        self.assertEqual(visit.state, 'done')

        # Totals and every PDF render.
        self.assertEqual(self.camp.patients_seen, 1)
        self.assertEqual(self.camp.medicines_dispensed, 10)
        for xmlid, record in [
            ('action_report_patient_card', visit),
            ('action_report_prescription_slip', consult),
            ('action_report_camp_summary', self.camp),
            ('action_report_camp_sponsor', self.camp),
        ]:
            html = self.env['ir.actions.report']._render_qweb_html(
                f'revive_medical_camp.{xmlid}', record.ids)[0]
            self.assertTrue(html, xmlid)

    def test_referral_letter(self):
        _patient, visit = self._register('Ravi')
        hospital = self.env['res.partner'].create({'name': 'Test Hospital', 'is_company': True})
        referral = self.env['camp.referral'].with_user(self.doctor).create({
            'visit_id': visit.id, 'hospital_id': hospital.id, 'reason': 'Cataract surgery'})
        visit.action_done()
        self.assertEqual(visit.state, 'referred')
        html = self.env['ir.actions.report']._render_qweb_html(
            'revive_medical_camp.action_report_referral_letter', referral.ids)[0]
        self.assertIn(b'Cataract surgery', html)

    def test_sponsor_report_hides_small_groups(self):
        for i in range(3):
            self._register(f'Zubaida Secretname{i}')
        stats = self.camp._report_stats(min_group=5)
        self.assertEqual(stats['patients'], 3)
        self.assertIsNone(stats['female'])      # 3 < 5 -> hidden
        self.assertEqual(stats['male'], 0)
        html = self.env['ir.actions.report']._render_qweb_html(
            'revive_medical_camp.action_report_camp_sponsor', self.camp.ids)[0]
        self.assertIn(b'&lt;5', html)
        self.assertNotIn(b'Secretname', html)  # no names in the sponsor report

    def test_expired_only_stock_is_blocked(self):
        _patient, visit = self._register('Bilal')
        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': visit.id,
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'quantity': 500})],
        })
        with self.assertRaises(UserError):
            consult.prescription_line_ids.with_user(self.pharmacist).action_dispense()

    def test_offline_shortage_is_recorded_not_failed(self):
        _patient, visit = self._register('Sana')
        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': visit.id,
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id, 'quantity': 200})],
        })
        line = consult.prescription_line_ids
        line.with_user(self.pharmacist).action_dispense(allow_shortage=True)
        self.assertEqual(line.dispensed_qty, 200)
        self.assertEqual(line.shortage_qty, 94)   # 6 + 100 good units available

    def test_consent_required_before_triage(self):
        patient = self.env['camp.patient'].create({'name': 'No Consent', 'sex': 'male', 'age_years': 40})
        visit = self.env['camp.visit'].create({'camp_id': self.camp.id, 'patient_id': patient.id})
        with self.assertRaises(ValidationError):
            self.env['camp.vitals'].with_user(self.nurse).create({'visit_id': visit.id, 'pulse': 80})

    def test_only_doctors_with_pmdc_prescribe(self):
        _patient, visit = self._register('Hina')
        with self.assertRaises(AccessError):
            self.env['camp.consultation'].with_user(self.nurse).create({'visit_id': visit.id})
        with self.assertRaises(ValidationError):
            self.env['camp.consultation'].with_user(self.doctor_no_pmdc).create({'visit_id': visit.id})

    def test_tokens_and_duplicate_registration(self):
        _p1, v1 = self._register('A')
        _p2, v2 = self._register('B')
        self.assertEqual((v1.token_no, v2.token_no), (1, 2))

    def test_access_is_separated(self):
        _patient, visit = self._register('Private')
        # A ministry/staff user with no camp role cannot see patients at all.
        with self.assertRaises(AccessError):
            self.env['camp.patient'].with_user(self.ministry).search([])
        # Registration staff from another camp's team cannot see this camp's visits.
        self.assertFalse(self.env['camp.visit'].with_user(self.outsider_reg).search([('id', '=', visit.id)]))
        # The coordinator sees every camp.
        self.assertTrue(self.env['camp.visit'].with_user(self.coordinator).search([('id', '=', visit.id)]))
        # Pharmacists cannot write diagnoses.
        with self.assertRaises(AccessError):
            self.env['camp.consultation'].with_user(self.pharmacist).create({'visit_id': visit.id})

    def test_sync_uuid_is_unique(self):
        patient = self.env['camp.patient'].create({'name': 'Dup', 'sex': 'male', 'client_uuid': 'abc-1'})
        self.assertTrue(patient)
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env['camp.patient'].create({'name': 'Dup2', 'sex': 'male', 'client_uuid': 'abc-1'})
