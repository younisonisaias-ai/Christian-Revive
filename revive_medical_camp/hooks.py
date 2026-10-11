"""Load the ICD-10-CM diagnosis list (about 10,400 codes) into camp.diagnosis.code.

Source: ICD-10-CM 2025 code descriptions, US National Center for Health
Statistics (CDC) - public domain. Only the 3- and 4-character codes are
loaded (the level used at camps); external-cause codes V00-Y99 are left out.
Codes that already exist (the camp list, or codes added by doctors) are kept
as they are.
"""
import csv
import logging
import os

from psycopg2.extras import execute_values

_logger = logging.getLogger(__name__)

CSV_PATH = os.path.join(os.path.dirname(__file__), 'data', 'icd10cm_2025.csv')

# ICD-10 chapters by code range, for grouping in Odoo.
CHAPTERS = [
    ('A00', 'B99', 'Infections'), ('C00', 'D49', 'Cancers and tumours'), ('D50', 'D89', 'Blood'),
    ('E00', 'E89', 'Endocrine and nutrition'), ('F01', 'F99', 'Mental health'), ('G00', 'G99', 'Nervous system'),
    ('H00', 'H59', 'Eye'), ('H60', 'H95', 'Ear'), ('I00', 'I99', 'Heart and circulation'),
    ('J00', 'J99', 'Respiratory'), ('K00', 'K95', 'Digestive and teeth'), ('L00', 'L99', 'Skin'),
    ('M00', 'M99', 'Bones and joints'), ('N00', 'N99', 'Urinary and reproductive'), ('O00', 'O9A', 'Pregnancy'),
    ('P00', 'P96', 'Newborn'), ('Q00', 'Q99', 'Birth defects'), ('R00', 'R99', 'Symptoms'),
    ('S00', 'T88', 'Injuries and poisoning'), ('U00', 'U85', 'Special codes'), ('Z00', 'Z99', 'Health services'),
]


def chapter_of(code):
    head = code[:3]
    for low, high, name in CHAPTERS:
        if low <= head <= high:
            return name
    return 'Other'


def load_icd10_catalog(env):
    cr = env.cr
    with open(CSV_PATH, encoding='utf-8') as f:
        rows = [(r['code'], r['name'], chapter_of(r['code'])) for r in csv.DictReader(f)]
    uid = env.uid
    execute_values(cr, """
        INSERT INTO camp_diagnosis_code (code, name, chapter, source, favourite, active,
                                         create_uid, create_date, write_uid, write_date)
        VALUES %s
        ON CONFLICT (code) DO NOTHING
    """, [(code, name, chapter, 'icd10', False, True, uid, uid) for code, name, chapter in rows],
        template="(%s, %s, %s, %s, %s, %s, %s, now() at time zone 'utc', %s, now() at time zone 'utc')",
        page_size=1000)
    _logger.info('Medical camp: ICD-10 list checked (%s codes in the file)', len(rows))
    env['camp.diagnosis.code'].invalidate_model()


def post_init_hook(env):
    env.cr.execute("UPDATE camp_diagnosis_code SET source = 'camp' WHERE source IS NULL OR source = 'custom'")
    load_icd10_catalog(env)
