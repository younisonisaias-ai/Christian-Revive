"""Run without Odoo: python -m unittest discover -s backend/church_report_mobile -p test_report_rules.py"""
import unittest
from datetime import datetime
from report_rules import validate, date_domain, jobs, member_filter

class ReportRulesTests(unittest.TestCase):
    def test_inclusive_dates_use_church_timezone(self):
        opts = validate({'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        self.assertEqual(date_domain('date', opts, 'Asia/Karachi'), [
            ('date', '>=', datetime(2026, 9, 30, 19)),
            ('date', '<', datetime(2026, 10, 31, 19))])
        self.assertEqual(date_domain('date', opts, datetime_field=False), [
            ('date', '>=', '2026-10-01'), ('date', '<=', '2026-10-31')])

    def test_dst_uses_calendar_midnights(self):
        opts = validate({'date_from': '2026-03-08', 'date_to': '2026-03-08'})
        self.assertEqual(date_domain('date', opts, 'America/New_York'), [
            ('date', '>=', datetime(2026, 3, 8, 5)),
            ('date', '<', datetime(2026, 3, 9, 4))])

    def test_private_jobs_require_explicit_detailed_care(self):
        self.assertEqual(jobs(validate({'sections': ['care'], 'detailed': True})), [])
        self.assertEqual(jobs(validate({'sections': ['care'], 'include_sensitive': True})), [])
        self.assertEqual(jobs(validate({'sections': ['care'], 'detailed': True, 'include_sensitive': True})), ['prayers', 'notes'])
        self.assertEqual(jobs(validate({'sections': ['giving'], 'detailed': True})), ['donations', 'pledges'])

    def test_rejects_invalid_scopes_and_flags(self):
        for options in ({'sections': []}, {'sections': ['unknown']}, {'date_from': '2026-10-01'},
                        {'date_from': '2026-10-02', 'date_to': '2026-10-01'},
                        {'include_sensitive': 'false'}, {'detailed': 1}):
            with self.assertRaises(ValueError): validate(options)
        self.assertEqual(date_domain('date', validate({})), [])

    def test_chosen_members_limit_every_section(self):
        opts = validate({'member_ids': [7, 3, 7]})
        self.assertEqual(opts['member_ids'], [3, 7])
        self.assertEqual(member_filter('donations', opts['member_ids']), [('partner_id', 'in', [3, 7])])
        self.assertEqual(member_filter('members', []), [])
        for bad in ({'member_ids': 'all'}, {'member_ids': [0]}, {'member_ids': [True]},
                    {'member_ids': list(range(1, 502))}):
            with self.assertRaises(ValueError): validate(bad)

if __name__ == '__main__': unittest.main()
