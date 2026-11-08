from odoo.tests.common import TransactionCase


class TestCollegeCertificates(TransactionCase):

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

        cls.other_student = cls.env['college.student'].create(
            {'name': 'Ruth', 'email': 'ruth@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create(
            {'student_id': cls.other_student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _token(self, student):
        code = student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']

    def _finish_lesson(self, token, lesson):
        Progress = self.env['college.lesson.progress']
        result = Progress.app_college_my_progress_save(token, lesson.id, completed=True)
        self.assertTrue(result['success'], result)

    def test_not_eligible_until_every_lesson_is_done(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        Certificate = self.env['college.certificate']
        result = Certificate.app_college_my_certificate(token, self.enrollment.id)
        self.assertFalse(result['success'])
        self.assertEqual(self.env['college.certificate'].search_count([]), 0)

    def test_issued_once_every_lesson_is_done(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        Certificate = self.env['college.certificate']
        result = Certificate.app_college_my_certificate(token, self.enrollment.id)
        self.assertTrue(result['success'], result)
        cert = result['certificate']
        self.assertEqual(cert['student_name'], 'Sarah')
        self.assertEqual(cert['course_name'], 'Old Testament Survey')
        self.assertEqual(cert['program_name'], 'Diploma')
        self.assertEqual(cert['term_name'], 'Fall')
        self.assertTrue(cert['issued_date'])
        self.assertRegex(cert['verification_code'], r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$')

    def test_fetching_twice_returns_the_same_certificate(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        Certificate = self.env['college.certificate']
        first = Certificate.app_college_my_certificate(token, self.enrollment.id)['certificate']
        second = Certificate.app_college_my_certificate(token, self.enrollment.id)['certificate']
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['verification_code'], second['verification_code'])
        self.assertEqual(Certificate.search_count([('enrollment_id', '=', self.enrollment.id)]), 1)

    def test_marking_a_lesson_undone_again_does_not_revoke_an_issued_certificate(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        Certificate = self.env['college.certificate']
        issued = Certificate.app_college_my_certificate(token, self.enrollment.id)['certificate']
        self.env['college.lesson.progress'].app_college_my_progress_save(token, self.lesson1.id, completed=False)
        still_there = Certificate.app_college_my_certificate(token, self.enrollment.id)
        self.assertTrue(still_there['success'])
        self.assertEqual(still_there['certificate']['id'], issued['id'])

    def test_cannot_fetch_a_certificate_for_someone_elses_enrollment(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        other_token = self._token(self.other_student)
        Certificate = self.env['college.certificate']
        result = Certificate.app_college_my_certificate(other_token, self.enrollment.id)
        self.assertFalse(result['success'])

    def test_public_verify_finds_a_real_certificate(self):
        token = self._token(self.student)
        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        Certificate = self.env['college.certificate']
        issued = Certificate.app_college_my_certificate(token, self.enrollment.id)['certificate']

        exact = Certificate.app_college_verify_certificate(issued['verification_code'])
        self.assertTrue(exact['success'], exact)
        self.assertEqual(exact['certificate']['student_name'], 'Sarah')

        # Typed without the dashes, or lowercase, still matches.
        loose = Certificate.app_college_verify_certificate(issued['verification_code'].replace('-', '').lower())
        self.assertTrue(loose['success'], loose)
        self.assertEqual(loose['certificate']['course_name'], 'Old Testament Survey')

    def test_public_verify_rejects_a_made_up_code(self):
        result = self.env['college.certificate'].app_college_verify_certificate('NOT-A-REAL-CODE')
        self.assertFalse(result['success'])

    def test_self_detail_reports_eligible_and_issued_flags(self):
        token = self._token(self.student)
        before = self.student._app_self_detail()['enrollments'][0]
        self.assertFalse(before['certificate_eligible'])
        self.assertFalse(before['certificate_issued'])

        self._finish_lesson(token, self.lesson1)
        self._finish_lesson(token, self.lesson2)
        eligible = self.student._app_self_detail()['enrollments'][0]
        self.assertTrue(eligible['certificate_eligible'])
        self.assertFalse(eligible['certificate_issued'])

        self.env['college.certificate'].app_college_my_certificate(token, self.enrollment.id)
        issued = self.student._app_self_detail()['enrollments'][0]
        self.assertTrue(issued['certificate_issued'])
