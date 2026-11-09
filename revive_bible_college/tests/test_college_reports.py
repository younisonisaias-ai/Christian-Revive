import base64
import io
import json
import zipfile

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, new_test_user

from .test_college_video import _VideoSetup


class TestCollegeReports(_VideoSetup, TransactionCase):
    """One course with two videos (100 s each, from _make_course), a
    reading and a quiz. Sarah studies; Ruth never starts."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()
        cls.reading = cls.env['college.course.content'].create(
            {'name': 'Reading', 'module_id': cls.module.id, 'content_type': 'text', 'body': 'Read me.'})
        cls.quiz = cls.env['college.quiz'].create({'name': 'Exodus check'})
        cls.q_single = cls.env['college.quiz.question'].create({
            'quiz_id': cls.quiz.id, 'text': 'Who led Israel?', 'option_ids': [
                (0, 0, {'text': 'Moses', 'is_correct': True}), (0, 0, {'text': 'Joshua'})]})
        cls.q_multi = cls.env['college.quiz.question'].create({
            'quiz_id': cls.quiz.id, 'question_type': 'multiple', 'text': 'Which are Gospels?', 'option_ids': [
                (0, 0, {'text': 'Mark', 'is_correct': True}), (0, 0, {'text': 'Acts'}), (0, 0, {'text': 'Romans'})]})
        cls.quiz_lesson = cls.env['college.course.content'].create(
            {'name': 'Quiz', 'module_id': cls.module.id, 'content_type': 'quiz', 'quiz_id': cls.quiz.id})
        cls.ruth = cls.env['college.student'].create({'name': 'Ruth', 'email': 'ruth@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create({'student_id': cls.ruth.id, 'course_id': cls.course.id, 'term_id': cls.term.id})
        cls.vq = cls.env['college.video.question'].create({
            'content_id': cls.youtube.id, 'pause_time': '0:30', 'text': 'Who spoke from the bush?',
            'option_ids': [(0, 0, {'text': 'God', 'is_correct': True}), (0, 0, {'text': 'Aaron'})]})

    def setUp(self):
        super().setUp()
        self.sarah_token = self._token(self.student)
        self.ruth_token = self._token(self.ruth)
        Progress = self.env['college.lesson.progress']
        # Sarah watches all of the YouTube video and only the first half of the other.
        Progress.app_college_my_progress_save(self.sarah_token, self.youtube.id, watched='0-19', duration=100)
        Progress.app_college_my_progress_save(self.sarah_token, self.lesson.id, watched='0-9', duration=100)
        Progress.app_college_my_progress_save(self.sarah_token, self.reading.id, completed=True)
        Quiz = self.env['college.quiz']
        moses = self.q_single.option_ids.filtered('is_correct').id
        joshua = (self.q_single.option_ids - self.q_single.option_ids.filtered('is_correct')).id
        mark, acts, romans = self.q_multi.option_ids.ids
        Quiz.app_college_my_quiz_submit(self.sarah_token, self.quiz_lesson.id, answers={
            self.q_single.id: joshua, self.q_multi.id: [mark, acts]})
        Quiz.app_college_my_quiz_submit(self.sarah_token, self.quiz_lesson.id, answers={
            self.q_single.id: moses, self.q_multi.id: [mark]})
        Quiz.app_college_my_quiz_submit(self.ruth_token, self.quiz_lesson.id, answers={
            self.q_single.id: joshua, self.q_multi.id: [acts, romans]})
        VQ = self.env['college.video.question']
        aaron = self.vq.option_ids.filtered(lambda o: not o.is_correct).id
        VQ.app_college_my_video_answer(self.sarah_token, self.vq.id, aaron)
        self.env.flush_all()
        # The quiz attempts above were Ruth's only activity; keep her "never started".
        self.env['college.lesson.progress'].search([('student_id', '=', self.ruth.id)]).unlink()
        self.env.flush_all()

    def progress_row(self, student):
        return self.env['college.report.progress'].search([('student_id', '=', student.id)])

    def test_student_progress_adds_up_lessons_videos_and_quizzes(self):
        row = self.progress_row(self.student)
        self.assertEqual(row.lessons_total, 4)
        self.assertEqual(row.lessons_done, 3)  # the full video, the reading, the passed quiz
        self.assertEqual(row.percent_done, 75.0)
        self.assertEqual(row.avg_watched, 75.0)  # (100 + 50) / 2 videos
        self.assertEqual(row.quizzes_taken, 1)
        self.assertEqual(row.avg_quiz, 100.0)  # best attempt
        self.assertFalse(row.has_certificate)
        self.assertTrue(row.last_active)
        ruth = self.progress_row(self.ruth)
        self.assertEqual((ruth.lessons_done, ruth.avg_watched, ruth.avg_quiz), (0, 0.0, 0.0))
        self.assertFalse(ruth.last_active)

    def test_falling_behind_finds_the_inactive_and_never_started(self):
        Report = self.env['college.report.progress']
        behind = Report.search([('falling_behind', '=', True)])
        self.assertEqual(behind.student_id, self.ruth)
        self.assertTrue(self.progress_row(self.ruth).falling_behind)
        self.assertFalse(self.progress_row(self.student).falling_behind)
        # Three weeks without activity counts too.
        self.env.cr.execute("UPDATE college_lesson_progress SET write_date = now() - interval '21 days' WHERE student_id = %s",
                            [self.student.id])
        self.env.invalidate_all()
        self.assertEqual(Report.search([('falling_behind', '=', True)]).student_id, self.student | self.ruth)
        self.assertEqual(Report.search([('falling_behind', '!=', True)]), Report.browse())
        # Someone who withdrew isn't "falling behind".
        self.env['college.enrollment'].search([('student_id', '=', self.ruth.id)]).state = 'withdrawn'
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertEqual(Report.search([('falling_behind', '=', True)]).student_id, self.student)

    def test_videos_show_who_started_finished_and_how_much(self):
        Report = self.env['college.report.video']
        full = Report.search([('content_id', '=', self.youtube.id)])
        self.assertEqual((full.students_enrolled, full.students_started, full.students_finished), (2, 1, 1))
        self.assertEqual(full.finished_percent, 50.0)
        self.assertEqual(full.avg_watched, 100.0)
        half = Report.search([('content_id', '=', self.lesson.id)])
        self.assertEqual((half.students_started, half.students_finished, half.avg_watched), (1, 0, 50.0))
        self.assertFalse(Report.search([('content_id', '=', self.reading.id)]))  # videos only

    def test_where_students_stop_watching(self):
        half = self.env['college.report.video'].search([('content_id', '=', self.lesson.id)])
        bars, viewers, length = half._dropoff()
        self.assertEqual((viewers, length), (1, 100.0))
        self.assertEqual([count for _start, _end, count in bars], [1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual((bars[5][0], bars[5][1]), (50.0, 60.0))
        html = str(half.dropoff_html)
        self.assertIn('0:50 – 1:00', html)
        self.assertIn('0 of 1', html)
        self.assertIn('1 of 1', html)
        unwatched = self.env['college.course.content'].create(
            {'name': 'New', 'module_id': self.module.id, 'content_type': 'video'})
        self.env.flush_all()
        report = self.env['college.report.video'].search([('content_id', '=', unwatched.id)])
        self.assertIn('No watching recorded yet', str(report.dropoff_html))

    def test_quiz_questions_hardest_first_with_the_most_common_wrong_answer(self):
        Report = self.env['college.report.quiz.question']
        rows = Report.search([])
        self.assertEqual(set(rows.mapped('question_id').ids), {self.q_multi.id, self.q_single.id})
        single = rows.filtered(lambda r: r.question_id == self.q_single)
        multi = rows.filtered(lambda r: r.question_id == self.q_multi)
        # Hardest first: an easier question sorts after them both.
        easy = self.env['college.quiz.question'].create({
            'quiz_id': self.quiz.id, 'question_type': 'true_false', 'text': 'Easy?', 'tf_answer': 'true'})
        self.env['college.quiz'].app_college_my_quiz_submit(self.ruth_token, self.quiz_lesson.id, answers={easy.id: True})
        self.env.flush_all()
        self.assertEqual(Report.search([])[-1].question_id, easy)
        self.assertEqual((single.answers, single.fully_right, single.percent_right), (3, 1, 33.3))
        self.assertEqual(single.common_wrong, 'Joshua (2×)')
        self.assertEqual((multi.answers, multi.fully_right), (3, 1))
        self.assertEqual(multi.common_wrong, 'Acts (2×)')
        # Part marks count: 0 (mark + acts cancel), 1, 0.
        self.assertEqual(multi.avg_marks, 33.3)

    def test_questions_during_videos(self):
        row = self.env['college.report.video.question'].search([])
        self.assertEqual(row.question_id, self.vq)
        self.assertEqual((row.answers, row.percent_right, row.pause_time), (1, 0.0, '0:30'))
        self.assertEqual(row.common_wrong, 'Aaron (1×)')
        self.assertEqual(row.course_id, self.course)

    def _xlsx_text(self, action):
        attachment = self.env['ir.attachment'].browse(int(action['url'].split('/')[3].split('?')[0]))
        data = base64.b64decode(attachment.datas)
        self.assertTrue(data.startswith(b'PK'))
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            return book.read('xl/sharedStrings.xml').decode()

    def test_download_excel_gives_the_rows_with_readable_columns(self):
        Report = self.env['college.report.progress']
        action = Report.browse().action_download_excel()  # nothing ticked: every row
        self.assertEqual(action['type'], 'ir.actions.act_url')
        self.assertTrue(action['url'].endswith('?download=true'))
        text = self._xlsx_text(action)
        for expected in ('Student', 'Videos watched (%)', 'Sarah', 'Ruth', 'Old Testament Survey', 'No'):
            self.assertIn(expected, text)
        only_ruth = self._xlsx_text(self.progress_row(self.ruth).action_download_excel())
        self.assertIn('Ruth', only_ruth)
        self.assertNotIn('Sarah', only_ruth)
        # Downloading again replaces the last file instead of piling them up.
        exports = self.env['ir.attachment'].search([('description', '=', 'college-report-export'),
                                                    ('res_model', '=', 'college.report.progress')])
        self.assertEqual(len(exports), 1)

    def test_every_report_downloads(self):
        for model in ('college.report.video', 'college.report.quiz.question', 'college.report.video.question'):
            text = self._xlsx_text(self.env[model].browse().action_download_excel())
            self.assertIn(self.env[model]._excel_columns()[0][1], text, model)

    def test_staff_and_admins_can_read_reports_others_cannot(self):
        staff = new_test_user(self.env, login='report-staff', groups='base.group_user,revive_bible_college.group_college_staff')
        admin = new_test_user(self.env, login='report-admin', groups='base.group_user,revive_bible_college.group_college_admin')
        other = new_test_user(self.env, login='report-other', groups='base.group_user')
        for user in (staff, admin):
            rows = self.env['college.report.progress'].with_user(user).search([])
            self.assertEqual(len(rows), 2)
            self.assertTrue(self.env['college.report.quiz.question'].with_user(user).search([]).mapped('common_wrong'))
            action = self.env['college.report.video'].with_user(user).browse().action_download_excel()
            attachment = self.env['ir.attachment'].with_user(user).browse(int(action['url'].split('/')[3].split('?')[0]))
            self.assertTrue(attachment.datas)  # the person who downloaded can open their file
        with self.assertRaises(AccessError):
            self.env['college.report.progress'].with_user(other).search([])

    def test_private_notes_are_in_no_report(self):
        self.env['college.lesson.note'].app_college_my_note_save(self.sarah_token, self.youtube.id, 12, 'My secret thought')
        for model in ('college.report.progress', 'college.report.video', 'college.report.quiz.question',
                      'college.report.video.question'):
            records = self.env[model].search([])
            self.assertNotIn('My secret thought', json.dumps(records.read(), default=str), model)
            self.assertNotIn('note', ' '.join(self.env[model]._fields), model)
