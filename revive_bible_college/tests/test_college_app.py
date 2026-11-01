import importlib.util
import os

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestCollegeApp(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Homiletics', 'program_id': cls.program.id})
        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.enrollment = cls.env['college.enrollment'].create(
            {'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _as_staff(self, role, model='college.program'):
        employee = self.env['hr.employee'].create({'name': role, 'staff_role': role, 'is_app_active': True})
        token = self.env['church.app.session']._issue('staff', employee=employee)
        return self.env[model].with_context(app_staff_session_token=token)

    def test_who_may_use_staff_screens(self):
        self.assertTrue(self._as_staff('college_staff').app_college_get_lookups()['success'])
        self.assertTrue(self._as_staff('college_admin').app_college_get_lookups()['success'])
        self.assertTrue(self._as_staff('admin').app_college_get_lookups()['success'])
        self.assertFalse(self._as_staff('pastor').app_college_get_lookups()['success'])
        self.assertFalse(self.env['college.program'].app_college_get_lookups()['success'])

    def test_lookups_say_which_terms_are_open(self):
        terms = self._as_staff('admin').app_college_get_lookups()['terms']
        self.assertEqual([t['state'] for t in terms if t['id'] == self.term.id], ['active'])

    def test_ungraded_is_not_a_fail(self):
        self.assertFalse(self.enrollment.letter_grade)
        self.enrollment.numeric_grade = 30
        self.assertEqual(self.enrollment.letter_grade, 'F')
        self.enrollment.numeric_grade = 92
        self.assertEqual(self.enrollment.letter_grade, 'A')
        self.enrollment.numeric_grade = 0
        self.assertFalse(self.enrollment.letter_grade)

    def test_a_typed_letter_survives_with_no_score(self):
        self.enrollment.letter_grade = 'F'
        self.assertEqual(self.enrollment.letter_grade, 'F')
        self.enrollment.action_submit_grade()
        self.assertEqual(self.enrollment.grade_state, 'submitted')

    def test_cannot_submit_an_empty_grade(self):
        with self.assertRaises(UserError):
            self.enrollment.action_submit_grade()
        self.assertEqual(self.enrollment.grade_state, 'draft')

    def test_records_have_real_names(self):
        self.assertEqual(self.enrollment.display_name, 'Sarah, Homiletics')
        sermon = self.env['college.sermon'].create({'student_id': self.student.id, 'title': 'Grace'})
        self.assertEqual(sermon.display_name, 'Grace')
        placement = self.env['college.placement'].create({'student_id': self.student.id, 'site_name': "St. Peter's"})
        self.assertEqual(placement.display_name, "St. Peter's")
        clearance = self.env['college.graduation.clearance'].create({'student_id': self.student.id})
        self.assertEqual(clearance.display_name, 'Sarah')

    def test_repair_clears_only_ungraded_fails(self):
        other = self.env['college.course'].create({'name': 'Other'})
        real_fail = self.env['college.enrollment'].create(
            {'student_id': self.student.id, 'course_id': other.id, 'term_id': self.term.id, 'numeric_grade': 30})
        self.env.flush_all()
        self.env.cr.execute("UPDATE college_enrollment SET letter_grade = 'F' WHERE id = %s", [self.enrollment.id])
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.1.10.0', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('college_repair', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.9.0')
        self.env.invalidate_all()
        self.assertFalse(self.enrollment.letter_grade)
        self.assertEqual(real_fail.letter_grade, 'F')

    def test_applicant_data_includes_the_student_number(self):
        applicant = self.env['college.applicant'].create(
            {'name': 'Lydia', 'email': 'lydia@example.com', 'program_id': self.program.id})
        applicant.action_submit()
        applicant.action_under_review()
        applicant.action_accept()
        applicant.action_enroll()
        data = self.env['college.applicant'].app_college_check_application(applicant.applicant_code, 'lydia@example.com')
        self.assertEqual(data['applicant']['student_code'], applicant.student_id.student_code)

    def test_assignment_list_returns_what_the_student_submitted(self):
        assignment = self.env['college.assignment'].create(
            {'name': 'Essay', 'course_id': self.course.id, 'term_id': self.term.id})
        Assignment = self.env['college.assignment']
        result = Assignment.app_college_student_submit_assignment(
            self.student.student_code, 'sarah@example.com', assignment.id, text_answer='My answer')
        self.assertTrue(result['success'])
        rows = Assignment.app_college_student_assignments(self.student.student_code, 'sarah@example.com')['assignments']
        self.assertEqual(rows[0]['text_answer'], 'My answer')
