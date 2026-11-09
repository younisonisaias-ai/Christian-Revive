from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.revive_bible_college.models.college_video_question import parse_clock

from .test_college_video import _VideoSetup


class TestCollegeVideoQuestions(_VideoSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()
        cls.Question = cls.env['college.video.question']
        cls.q_late = cls.Question.create({
            'content_id': cls.youtube.id, 'pause_time': '12:10', 'text': 'Who was the firstborn spared by?',
            'option_ids': [(0, 0, {'text': 'The blood of the lamb', 'is_correct': True}), (0, 0, {'text': 'Gold'})],
            'explanation': 'Exodus 12:13.',
        })
        cls.q_early = cls.Question.create({
            'content_id': cls.youtube.id, 'pause_time': '4:30', 'text': 'Who led Israel out of Egypt?',
            'option_ids': [(0, 0, {'text': 'Joshua'}), (0, 0, {'text': 'Moses', 'is_correct': True})],
        })

    def _lesson(self, lesson_id):
        modules = self.student._app_self_detail()['enrollments'][0]['modules']
        return {l['id']: l for l in modules[0]['lessons']}[lesson_id]

    def test_times_are_read_like_a_clock(self):
        self.assertEqual(parse_clock('4:30'), 270)
        self.assertEqual(parse_clock(' 1:02:30 '), 3750)
        self.assertEqual(parse_clock('75:00'), 4500)
        for bad in ('4.30', '4:3', '4:60', '1:60:00', 'soon', '', False):
            self.assertIsNone(parse_clock(bad), bad)
        self.assertEqual(self.q_early.pause_seconds, 270)

    def test_a_question_needs_a_real_time(self):
        with self.assertRaises(ValidationError):
            self.Question.create({'content_id': self.youtube.id, 'pause_time': 'halfway', 'text': 'Q?'})

    def test_the_app_gets_questions_in_time_order_without_the_correct_answer(self):
        questions = self._lesson(self.youtube.id)['video_questions']
        self.assertEqual([q['seconds'] for q in questions], [270, 730])
        self.assertEqual(questions[0]['text'], 'Who led Israel out of Egypt?')
        self.assertEqual([o['text'] for o in questions[0]['options']], ['Joshua', 'Moses'])
        self.assertFalse(questions[0]['answered'])
        for question in questions:
            for option in question['options']:
                self.assertEqual(set(option), {'id', 'text'})  # never is_correct
        self.assertNotIn('explanation', questions[0])

    def test_a_question_with_no_answers_yet_is_not_sent(self):
        self.Question.create({'content_id': self.youtube.id, 'pause_time': '1:00', 'text': 'Unfinished'})
        self.assertEqual(len(self._lesson(self.youtube.id)['video_questions']), 2)

    def test_answering_checks_on_the_server_and_explains(self):
        token = self._token(self.student)
        moses = self.q_early.option_ids.filtered('is_correct')
        joshua = self.q_early.option_ids - moses
        wrong = self.Question.app_college_my_video_answer(token, self.q_early.id, joshua.id)
        self.assertEqual(wrong, {'success': True, 'is_correct': False, 'correct_option_id': moses.id, 'explanation': ''})
        right = self.Question.app_college_my_video_answer(token, self.q_late.id, self.q_late.option_ids.filtered('is_correct').id)
        self.assertTrue(right['is_correct'])
        self.assertEqual(right['explanation'], 'Exodus 12:13.')
        self.assertTrue(all(q['answered'] for q in self._lesson(self.youtube.id)['video_questions']))

    def test_answering_again_keeps_one_answer_the_latest(self):
        token = self._token(self.student)
        moses = self.q_early.option_ids.filtered('is_correct')
        self.Question.app_college_my_video_answer(token, self.q_early.id, (self.q_early.option_ids - moses).id)
        self.Question.app_college_my_video_answer(token, self.q_early.id, moses.id)
        answers = self.env['college.video.question.answer'].search([('question_id', '=', self.q_early.id)])
        self.assertEqual(len(answers), 1)
        self.assertTrue(answers.is_correct)
        self.assertEqual(self.q_early.answer_count, 1)
        self.assertEqual(self.q_early.correct_percent, 100.0)

    def test_answers_are_refused_outside_the_students_courses_or_questions(self):
        token = self._token(self.student)
        moses = self.q_early.option_ids.filtered('is_correct')
        Q = self.Question
        self.assertEqual(Q.app_college_my_video_answer('bad', self.q_early.id, moses.id)['error'], 'Please sign in again')
        # An answer from a different question.
        self.assertEqual(Q.app_college_my_video_answer(token, self.q_late.id, moses.id)['error'], 'Not found')
        self.assertEqual(Q.app_college_my_video_answer(token, 999999, moses.id)['error'], 'Not found')
        other_course = self.env['college.course'].create({'name': 'Homiletics', 'program_id': self.program.id})
        other_module = self.env['college.course.module'].create({'name': 'M', 'course_id': other_course.id})
        other = self.env['college.course.content'].create({'name': 'Other', 'module_id': other_module.id, 'content_type': 'video'})
        other_q = Q.create({'content_id': other.id, 'pause_time': '0:10', 'text': 'Q', 'option_ids': [(0, 0, {'text': 'A', 'is_correct': True})]})
        self.assertEqual(Q.app_college_my_video_answer(token, other_q.id, other_q.option_ids.id)['error'], 'Not found')
        self.assertFalse(self.env['college.video.question.answer'].search_count([('student_id', '=', self.student.id)]))

    def test_practice_answers_never_touch_progress_grades_or_badges(self):
        token = self._token(self.student)
        self.Question.app_college_my_video_answer(token, self.q_early.id, self.q_early.option_ids.filtered('is_correct').id)
        self.assertFalse(self.env['college.lesson.progress'].search_count([('student_id', '=', self.student.id)]))
        self.assertFalse(self.env['college.badge.award'].search_count([('student_id', '=', self.student.id)]))
        self.assertFalse(self.env['college.quiz.attempt'].search_count([('student_id', '=', self.student.id)]))

    def test_the_lesson_button_opens_only_its_questions(self):
        action = self.youtube.action_view_video_questions()
        self.assertEqual(self.Question.search(action['domain']), self.q_early | self.q_late)
        self.assertEqual(action['context'], {'default_content_id': self.youtube.id})
        self.assertEqual(self.youtube.video_question_count, 2)

    def test_questions_go_with_their_lesson(self):
        token = self._token(self.student)
        self.Question.app_college_my_video_answer(token, self.q_early.id, self.q_early.option_ids[0].id)
        self.youtube.unlink()
        self.assertFalse(self.Question.search_count([]))
        self.assertFalse(self.env['college.video.question.answer'].search_count([]))

    def test_non_video_lessons_send_no_questions(self):
        text = self.env['college.course.content'].create({'name': 'Reading', 'module_id': self.module.id, 'content_type': 'text'})
        self.Question.create({'content_id': text.id, 'pause_time': '0:10', 'text': 'Q', 'option_ids': [(0, 0, {'text': 'A'})]})
        self.assertEqual(self._lesson(text.id)['video_questions'], [])
