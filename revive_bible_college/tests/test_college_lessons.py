import importlib.util
import os

from odoo.tests.common import TransactionCase


class TestCollegeLessons(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Old Testament Survey', 'program_id': cls.program.id})
        cls.other_course = cls.env['college.course'].create({'name': 'Other', 'program_id': cls.program.id})
        cls.module1 = cls.env['college.course.module'].create({'name': 'The Pentateuch', 'course_id': cls.course.id, 'sequence': 10})
        cls.module2 = cls.env['college.course.module'].create({'name': 'The Prophets', 'course_id': cls.course.id, 'sequence': 20})
        cls.video = cls.env['college.course.content'].create(
            {'name': 'The Exodus', 'course_id': cls.course.id, 'module_id': cls.module1.id, 'content_type': 'video', 'sequence': 1})
        cls.reading = cls.env['college.course.content'].create(
            {'name': 'Genesis overview', 'course_id': cls.course.id, 'module_id': cls.module1.id, 'content_type': 'text', 'sequence': 2})
        cls.other_lesson = cls.env['college.course.content'].create(
            {'name': 'Unrelated', 'course_id': cls.other_course.id, 'content_type': 'video'})
        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create({'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _token(self):
        code = self.student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(self.student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']

    def test_a_lesson_added_inside_a_module_takes_its_course_automatically(self):
        lesson = self.env['college.course.content'].create(
            {'name': 'New lesson', 'module_id': self.module1.id, 'content_type': 'text'})
        self.assertEqual(lesson.course_id, self.course)

    def test_a_lesson_with_no_module_still_needs_its_own_course(self):
        from psycopg2 import IntegrityError
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env['college.course.content'].create({'name': 'No module, no course', 'content_type': 'text'})

    def test_lessons_are_grouped_into_modules_in_order(self):
        detail = self.student._app_self_detail()
        modules = detail['enrollments'][0]['modules']
        self.assertEqual([m['name'] for m in modules], ['The Pentateuch', 'The Prophets'])
        self.assertEqual([l['name'] for l in modules[0]['lessons']], ['The Exodus', 'Genesis overview'])
        self.assertEqual(modules[1]['lessons'], [])

    def test_a_lesson_with_no_module_still_shows(self):
        stray = self.env['college.course.content'].create({'name': 'Stray note', 'course_id': self.course.id, 'content_type': 'text'})
        detail = self.student._app_self_detail()
        modules = detail['enrollments'][0]['modules']
        self.assertEqual(modules[-1]['name'], 'More')
        self.assertEqual([l['name'] for l in modules[-1]['lessons']], ['Stray note'])
        stray.unlink()

    def test_percent_complete(self):
        self.assertEqual(self.student._app_self_detail()['enrollments'][0]['percent_complete'], 0)
        token = self._token()
        Progress = self.env['college.lesson.progress']
        # A video is finished by watching it (see test_college_watch.py).
        self.assertTrue(Progress.app_college_my_progress_save(token, self.video.id, watched='0-23', duration=120)['completed'])
        enrollment = self.student._app_self_detail()['enrollments'][0]
        self.assertEqual(enrollment['percent_complete'], 50)
        self.assertEqual(enrollment['lessons_done'], 1)
        self.assertEqual(enrollment['lesson_count'], 2)
        self.assertTrue(Progress.app_college_my_progress_save(token, self.reading.id, completed=True)['success'])
        self.assertEqual(self.student._app_self_detail()['enrollments'][0]['percent_complete'], 100)

    def test_video_position_is_saved_and_updated(self):
        token = self._token()
        Progress = self.env['college.lesson.progress']
        Progress.app_college_my_progress_save(token, self.video.id, video_position=42.5)
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertEqual(lesson['video_position'], 42.5)
        self.assertFalse(lesson['completed'])
        Progress.app_college_my_progress_save(token, self.video.id, video_position=90.0)
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertEqual(lesson['video_position'], 90.0)

    def test_marking_complete_can_be_undone(self):
        token = self._token()
        Progress = self.env['college.lesson.progress']
        Progress.app_college_my_progress_save(token, self.video.id, watched='0-23', duration=120)
        self.assertTrue(self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]['completed'])
        Progress.app_college_my_progress_save(token, self.video.id, completed=False)
        self.assertFalse(self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]['completed'])

    def test_cannot_save_progress_without_a_token(self):
        result = self.env['college.lesson.progress'].app_college_my_progress_save('made-up', self.video.id, completed=True)
        self.assertFalse(result['success'])

    def test_cannot_save_progress_on_a_lesson_from_an_unenrolled_course(self):
        token = self._token()
        result = self.env['college.lesson.progress'].app_college_my_progress_save(token, self.other_lesson.id, completed=True)
        self.assertFalse(result['success'])

    def test_migration_backfills_lessons_with_no_module(self):
        orphan_course = self.env['college.course'].create({'name': 'Orphan Course', 'program_id': self.program.id})
        self.env.cr.execute(
            "INSERT INTO college_course_content (name, course_id, content_type, sequence, active, create_date, write_date, create_uid, write_uid) "
            "VALUES ('{\"en_US\": \"Old syllabus\"}'::jsonb, %s, 'document', 1, true, now(), now(), 1, 1)", [orphan_course.id])
        self.env.flush_all()
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '19.0.1.12.0', 'post-migrate.py')
        spec = importlib.util.spec_from_file_location('college_module_migration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.migrate(self.env.cr, '19.0.1.11.0')
        self.env.invalidate_all()
        new_module = self.env['college.course.module'].search([('course_id', '=', orphan_course.id)])
        self.assertEqual(len(new_module), 1)
        self.assertEqual(new_module.name, 'Course Materials')
        self.assertEqual(new_module.lesson_ids.mapped('name'), ['Old syllabus'])
        # A course that already has a module of its own is left alone, not given a second one.
        migrated_before = self.env['college.course.module'].search_count([('course_id', '=', self.course.id)])
        module.migrate(self.env.cr, '19.0.1.11.0')
        self.assertEqual(self.env['college.course.module'].search_count([('course_id', '=', self.course.id)]), migrated_before)
