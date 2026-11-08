from odoo.tests.common import TransactionCase


class TestCollegeStaffProgress(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Old Testament Survey', 'program_id': cls.program.id})
        cls.module = cls.env['college.course.module'].create({'name': 'The Pentateuch', 'course_id': cls.course.id})
        cls.lesson1 = cls.env['college.course.content'].create(
            {'name': 'Genesis overview', 'module_id': cls.module.id, 'content_type': 'text', 'body': 'Creation.'})
        cls.lesson2 = cls.env['college.course.content'].create(
            {'name': 'Exodus overview', 'module_id': cls.module.id, 'content_type': 'text', 'body': 'Deliverance.'})
        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.enrollment = cls.env['college.enrollment'].create(
            {'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _as_staff(self, role):
        employee = self.env['hr.employee'].create({'name': role, 'staff_role': role, 'is_app_active': True})
        token = self.env['church.app.session']._issue('staff', employee=employee)
        return self.env['college.student'].with_context(app_staff_session_token=token)

    def _token(self):
        code = self.student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(self.student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']

    def test_only_staff_can_view_student_progress(self):
        self.assertFalse(self.env['college.student'].app_college_get_student_progress(self.student.id)['success'])
        self.assertFalse(self._as_staff('pastor').app_college_get_student_progress(self.student.id)['success'])
        self.assertTrue(self._as_staff('college_staff').app_college_get_student_progress(self.student.id)['success'])
        self.assertTrue(self._as_staff('college_admin').app_college_get_student_progress(self.student.id)['success'])

    def test_a_missing_student_is_reported_not_found(self):
        result = self._as_staff('college_admin').app_college_get_student_progress(999999)
        self.assertFalse(result['success'])

    def test_progress_matches_the_students_own_view(self):
        token = self._token()
        self.env['college.lesson.progress'].app_college_my_progress_save(token, self.lesson1.id, completed=True)
        own = self.student._app_self_detail()
        staff = self._as_staff('college_admin').app_college_get_student_progress(self.student.id)
        self.assertTrue(staff['success'], staff)
        self.assertEqual(staff['enrollments'], own['enrollments'])
        self.assertEqual(staff['badges'], own['badges'])
        self.assertEqual(staff['enrollments'][0]['lessons_done'], 1)
        self.assertEqual([b['kind'] for b in staff['badges']], ['first_lesson'])
