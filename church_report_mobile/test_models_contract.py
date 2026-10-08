"""Exercise actual RPC method logic with a small mocked ORM, without Odoo."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

folder = Path(__file__).parent
fake_odoo = types.ModuleType('odoo')
fake_odoo.api = types.SimpleNamespace(model=lambda fn: fn)
fake_odoo.fields = types.SimpleNamespace()
fake_odoo.models = types.SimpleNamespace(AbstractModel=object)
package = types.ModuleType('_church_report_test')
package.__path__ = [str(folder)]
sys.modules['_church_report_test'] = package
saved_odoo = sys.modules.get('odoo')
sys.modules['odoo'] = fake_odoo
try:
    spec = importlib.util.spec_from_file_location('_church_report_test.models', folder / 'models.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
finally:
    if saved_odoo is None: sys.modules.pop('odoo', None)
    else: sys.modules['odoo'] = saved_odoo

class ReportContractTests(unittest.TestCase):
    def setUp(self):
        self.report = module.ChurchReportMobile()
        self.employee = types.SimpleNamespace(is_app_active=True, staff_role='admin')
        self.env = MagicMock()
        self.env.__getitem__.return_value.sudo.return_value.browse.return_value.exists.return_value = self.employee
        self.report.env = self.env

    def test_enabled_admin_only_and_invalid_ids_denied(self):
        self.assertIs(self.report._report_admin(1), self.employee)
        for invalid in (True, -1, 0, '1', None):
            self.assertIsNone(self.report._report_admin(invalid))
        self.employee.staff_role = 'pastor'
        self.assertEqual(self.report.app_report_page(1)['code'], 'denied')
        self.assertEqual(self.report.app_report_manifest(1)['code'], 'denied')
        self.employee.staff_role = 'admin'
        self.employee.is_app_active = False
        self.assertEqual(self.report.app_report_manifest(1)['code'], 'denied')

    def test_private_pages_denied_unless_selected_and_opted_in(self):
        for opts in ({'sections': ['care'], 'detailed': True},
                     {'sections': ['care'], 'include_sensitive': True},
                     {'sections': ['giving'], 'detailed': True, 'include_sensitive': True}):
            self.assertEqual(self.report.app_report_page(1, opts, 'prayers')['code'], 'denied')
            self.assertEqual(self.report.app_report_page(1, opts, 'notes')['code'], 'denied')

    def test_page_uses_keyset_cursor_and_lookahead(self):
        source = MagicMock()
        source.search.return_value = [types.SimpleNamespace(id=i) for i in (101, 102, 103)]
        self.report._report_source = MagicMock(return_value=(source, [('is_member', '=', True)]))
        self.report._report_row = lambda section, record, staff, opts: {'id': record.id}
        result = self.report.app_report_page(1, {'sections': ['membership'], 'detailed': True}, 'members', 100, 2)
        self.assertEqual(result, {'success': True, 'rows': [{'id': 101}, {'id': 102}], 'next_id': 102, 'has_more': True})
        source.search.assert_called_once_with([('is_member', '=', True), ('id', '>', 100)], order='id asc', limit=3)

    def test_invalid_cursor_and_page_size_rejected(self):
        opts = {'sections': ['membership'], 'detailed': True}
        for cursor, limit in ((-1, 100), (True, 100), (0, 201), (0, 0)):
            self.assertEqual(self.report.app_report_page(1, opts, 'members', cursor, limit)['code'], 'invalid')

    def test_member_care_status_removed_by_default(self):
        member = types.SimpleNamespace(id=1, app_get_member_detail=lambda *a, **k: {
            'success': True, 'member': {'id': 1, 'name': 'Sample', 'care_status': 'private', 'care_status_date': '2026-10-01'}})
        ordinary = self.report._report_row('members', member, 1, {'sensitive': False})
        self.assertEqual(ordinary, {'id': 1, 'name': 'Sample'})
        private = self.report._report_row('members', member, 1, {'sensitive': True})
        self.assertEqual(private['care_status'], 'private')

if __name__ == '__main__': unittest.main()
