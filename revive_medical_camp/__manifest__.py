{
    'name': 'Medical Camp Management',
    'version': '19.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Run free medical camps end to end: registration, triage, doctor, pharmacy, referrals, sponsor reports',
    'description': """
Medical Camp Management
=======================
A standalone module for running health camps:

* Camps with site, sponsors, specialities, team and budget
* Patient registration with consent, token number and QR card
* Triage vitals with automatic red flags (thresholds set by the medical lead)
* Doctor consultation with ICD-10 diagnoses and prescriptions from camp stock
* Pharmacy dispensing from Inventory, nearest expiry first, expired batches blocked
* Referral letters, health-talk sessions, camp summary and anonymised sponsor report
* Role-based access: coordinator, registration, nurse, doctor, pharmacist,
  follow-up, medical lead

Patient records are kept apart from every other app: no link to contacts,
membership, donations or any other module.
""",
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'product', 'stock', 'product_expiry'],
    'data': [
        'security/camp_security.xml',
        'security/ir.model.access.csv',
        'security/camp_rules.xml',
        'data/camp_sequence.xml',
        'data/camp_speciality_data.xml',
        'data/camp_flag_rule_data.xml',
        'data/camp_dose_template_data.xml',
        'data/camp_diagnosis_code_data.xml',
        'report/camp_report_actions.xml',
        'report/camp_prescription_slip.xml',
        'report/camp_referral_letter.xml',
        'report/camp_summary_report.xml',
        'report/camp_sponsor_report.xml',
        'views/camp_patient_views.xml',
        'views/camp_visit_views.xml',
        'views/camp_clinical_views.xml',
        'views/camp_config_views.xml',
        'views/camp_camp_views.xml',
        'views/res_users_views.xml',
        'views/camp_menus.xml',
    ],
    'demo': [
        'demo/camp_demo.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'revive_medical_camp/static/src/scss/camp_report_fonts.scss',
        ],
    },
    'application': True,
    'installable': True,
}
