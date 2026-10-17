from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCampDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Users = env['res.users'].with_context(no_reset_password=True)

        def user(login, *groups, **extra):
            return Users.create({'name': login.title(), 'login': login,
                                 'group_ids': [(6, 0, [env.ref(g).id for g in groups])], **extra})

        cls.coordinator = user('dash_coord', 'revive_medical_camp.group_camp_coordinator')
        cls.registration = user('dash_reg', 'revive_medical_camp.group_camp_registration')
        cls.nurse = user('dash_nurse', 'revive_medical_camp.group_camp_nurse')
        cls.doctor = user('dash_doc', 'revive_medical_camp.group_camp_doctor', camp_pmdc_number='54321-P')
        cls.pharmacist = user('dash_pharm', 'revive_medical_camp.group_camp_pharmacist')
        cls.medicine = env['product.product'].create({
            'name': 'Dash Amoxicillin', 'type': 'consu', 'is_storable': True,
            'tracking': 'lot', 'use_expiration_date': True})
        cls.formulary = env['camp.formulary'].create({
            'product_id': cls.medicine.id, 'strength': '250 mg',
            'default_dose_template_id': env.ref('revive_medical_camp.dose_1_0_1').id, 'default_days': 5})
        cls.camp = env['camp.camp'].create({'name': 'Dashboard Camp', 'state': 'running',
                                            'expected_patients': 4, 'area': 'Youhanabad'})
        cls.other_camp = env['camp.camp'].create({'name': 'Older Camp', 'state': 'closed',
                                                  'date_start': fields.Date.today() - timedelta(days=60)})
        for u, role in [(cls.registration, 'registration'), (cls.nurse, 'nurse'),
                        (cls.doctor, 'doctor'), (cls.pharmacist, 'pharmacist')]:
            env['camp.team.member'].create({'camp_id': cls.camp.id, 'user_id': u.id, 'role': role})
        now = fields.Datetime.now()
        lot_soon = env['stock.lot'].create({'name': 'DASH-SOON', 'product_id': cls.medicine.id,
                                            'expiration_date': now + timedelta(days=20)})
        env['stock.quant']._update_available_quantity(cls.medicine, cls.camp.stock_location_id, 12, lot_id=lot_soon)
        env['camp.budget.line'].create({'camp_id': cls.camp.id, 'category': 'transport',
                                        'planned': 5000, 'actual': 6000})

    def _register(self, name, sex='female', age=34):
        patient = self.env['camp.patient'].with_user(self.registration).create({
            'name': name, 'sex': sex, 'age_years': age, 'consent_care': True})
        return self.env['camp.visit'].with_user(self.registration).create(
            {'camp_id': self.camp.id, 'patient_id': patient.id})

    def test_dashboard_numbers(self):
        # One finished patient with a red flag and medicine, one waiting, one child waiting.
        done = self._register('Dash Asha')
        self.env['camp.vitals'].with_user(self.nurse).create(
            {'visit_id': done.id, 'bp_systolic': 190, 'bp_diastolic': 110})
        consult = self.env['camp.consultation'].with_user(self.doctor).create({
            'visit_id': done.id, 'complaint': 'Headache',
            'diagnosis_ids': [(6, 0, [self.env.ref('revive_medical_camp.icd_i10').id])],
            'prescription_line_ids': [(0, 0, {'formulary_id': self.formulary.id})]})
        consult.with_user(self.doctor).action_finish()
        consult.prescription_line_ids.with_user(self.pharmacist).action_dispense()
        self._register('Dash Bilal', sex='male', age=50)
        self._register('Dash Child', sex='male', age=6)

        data = self.env['camp.dashboard'].with_user(self.coordinator).get_dashboard(self.camp.id)
        kpis = data['kpis']
        self.assertEqual(data['mode'], 'camp')
        self.assertEqual(kpis['patients_seen'], 3)
        self.assertEqual(kpis['expected'], 4)
        self.assertEqual(kpis['progress'], 75.0)
        self.assertEqual(kpis['waiting_now'], 2)
        self.assertEqual(kpis['red_flags'], 1)
        self.assertEqual(kpis['medicines_units'], 10)
        stages = {s['key']: s['count'] for s in data['flow']['stages']}
        self.assertEqual((stages['done'], stages['registered']), (1, 2))
        self.assertEqual(len(data['flow']['longest']), 2)
        self.assertTrue(data['live'])
        clinical = data['clinical']
        self.assertEqual(clinical['diagnoses'][0]['value'], 1)
        self.assertEqual(clinical['sexes'], {'male': 2, 'female': 1, 'other': 0})
        self.assertEqual(clinical['children'], 1)
        self.assertEqual(sum(band['male'] + band['female'] for band in clinical['ages']), 3)
        pharmacy = data['pharmacy']
        self.assertEqual(pharmacy['top_medicines'][0]['value'], 10)
        # 12 in stock, 10 given: 2 left, below the low-stock line, lot expiring in 20 days.
        self.assertIn(self.formulary.display_name, [r['product'] for r in pharmacy['low_stock']])
        self.assertEqual(len(pharmacy['expiring']), 1)
        self.assertEqual(data['team']['per_doctor'][0]['value'], 1)
        money = data['money']
        self.assertEqual((money['planned'], money['actual']), (5000, 6000))
        self.assertEqual(money['used_percent'], 120.0)
        listed = {row['id'] for row in data['all_camps']['rows']}
        self.assertTrue({self.camp.id, self.other_camp.id} <= listed)

    def test_all_camps_and_default(self):
        # Works on a database that already holds real camps too.
        Dashboard = self.env['camp.dashboard'].with_user(self.coordinator)
        before = Dashboard.get_dashboard('all')['kpis']['patients_seen']
        self._register('Dash One')
        everything = Dashboard.get_dashboard('all')
        self.assertEqual(everything['mode'], 'all')
        self.assertEqual(everything['kpis']['patients_seen'], before + 1)
        self.assertEqual(everything['day']['kind'], 'camps')
        self.assertEqual(everything['pharmacy']['low_stock'], [])  # store is per camp only
        running = self.env['camp.camp'].search([('state', '=', 'running')])
        if running == self.camp:
            self.assertEqual(Dashboard.get_dashboard()['camp_id'], self.camp.id,
                             'the running camp opens first')

    def test_only_coordinators_and_lead(self):
        for person in (self.registration, self.nurse, self.doctor, self.pharmacist):
            with self.assertRaises(AccessError):
                self.env['camp.dashboard'].with_user(person).get_dashboard(self.camp.id)
