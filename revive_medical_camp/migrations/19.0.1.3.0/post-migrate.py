"""1.3.0: full ICD-10-CM list for doctors; the existing codes are the camp list."""
from odoo import SUPERUSER_ID, api

from odoo.addons.revive_medical_camp.hooks import load_icd10_catalog


def migrate(cr, version):
    cr.execute("UPDATE camp_diagnosis_code SET source = 'camp' WHERE source IS NULL OR source = 'custom'")
    load_icd10_catalog(api.Environment(cr, SUPERUSER_ID, {}))
