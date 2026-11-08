from odoo.tests.common import TransactionCase


class TestCollegeQuizzes(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Old Testament Survey', 'program_id': cls.program.id})
        cls.other_course = cls.env['college.course'].create({'name': 'Other', 'program_id': cls.program.id})
        cls.module = cls.env['college.course.module'].create({'name': 'The Pentateuch', 'course_id': cls.course.id})

        cls.quiz = cls.env['college.quiz'].create({'name': 'The Exodus', 'pass_score': 60.0})
        cls.q1 = cls.env['college.quiz.question'].create(
            {'quiz_id': cls.quiz.id, 'text': 'Who led Israel out of Egypt?', 'explanation': 'Moses led them out.'})
        cls.q1_right = cls.env['college.quiz.option'].create({'question_id': cls.q1.id, 'text': 'Moses', 'is_correct': True})
        cls.q1_wrong = cls.env['college.quiz.option'].create({'question_id': cls.q1.id, 'text': 'Joshua'})
        cls.q2 = cls.env['college.quiz.question'].create({'quiz_id': cls.quiz.id, 'text': 'What sea did they cross?'})
        cls.q2_right = cls.env['college.quiz.option'].create({'question_id': cls.q2.id, 'text': 'The Red Sea', 'is_correct': True})
        cls.q2_wrong = cls.env['college.quiz.option'].create({'question_id': cls.q2.id, 'text': 'The Dead Sea'})

        cls.lesson = cls.env['college.course.content'].create({
            'name': 'Quiz: The Exodus', 'module_id': cls.module.id, 'content_type': 'quiz', 'quiz_id': cls.quiz.id,
        })
        cls.other_lesson = cls.env['college.course.content'].create(
            {'name': 'Unrelated video', 'course_id': cls.other_course.id, 'content_type': 'video'})

        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create({'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _token(self):
        code = self.student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(self.student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']

    def test_a_question_with_no_correct_option_flags_itself_but_does_not_crash(self):
        question = self.env['college.quiz.question'].create({'quiz_id': self.quiz.id, 'text': 'Spare question'})
        self.assertFalse(question.has_correct_option)
        only_option = self.env['college.quiz.option'].create({'question_id': question.id, 'text': 'A'})
        self.assertFalse(question.has_correct_option)
        only_option.is_correct = True
        self.assertTrue(question.has_correct_option)

    def test_student_sees_questions_and_options_but_not_which_is_correct(self):
        token = self._token()
        result = self.env['college.quiz'].app_college_my_quiz(token, self.lesson.id)
        self.assertTrue(result['success'], result)
        quiz = result['quiz']
        self.assertEqual(quiz['name'], 'The Exodus')
        self.assertEqual(len(quiz['questions']), 2)
        for question in quiz['questions']:
            for option in question['options']:
                self.assertNotIn('is_correct', option)
        self.assertIsNone(quiz['best_score'])
        self.assertEqual(quiz['attempt_count'], 0)

    def test_grading_is_done_on_the_server_and_marks_the_lesson_complete_on_passing(self):
        token = self._token()
        Quiz = self.env['college.quiz']
        result = Quiz.app_college_my_quiz_submit(token, self.lesson.id, answers={
            self.q1.id: self.q1_right.id, self.q2.id: self.q2_right.id,
        })
        self.assertTrue(result['success'], result)
        self.assertEqual(result['score'], 100.0)
        self.assertTrue(result['passed'])
        by_question = {r['question_id']: r for r in result['results']}
        self.assertTrue(by_question[self.q1.id]['is_correct'])
        self.assertEqual(by_question[self.q1.id]['correct_option_id'], self.q1_right.id)
        self.assertEqual(by_question[self.q1.id]['explanation'], 'Moses led them out.')

        enrollment = self.student._app_self_detail()['enrollments'][0]
        lesson = enrollment['modules'][0]['lessons'][0]
        self.assertTrue(lesson['completed'])
        self.assertEqual(lesson['quiz_best_score'], 100.0)
        self.assertEqual(lesson['quiz_attempt_count'], 1)

    def test_failing_does_not_complete_the_lesson_but_a_later_pass_does(self):
        token = self._token()
        Quiz = self.env['college.quiz']
        first = Quiz.app_college_my_quiz_submit(token, self.lesson.id, answers={self.q1.id: self.q1_wrong.id, self.q2.id: self.q2_wrong.id})
        self.assertEqual(first['score'], 0.0)
        self.assertFalse(first['passed'])
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertFalse(lesson['completed'])

        second = Quiz.app_college_my_quiz_submit(token, self.lesson.id, answers={self.q1.id: self.q1_right.id, self.q2.id: self.q2_right.id})
        self.assertTrue(second['passed'])
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertTrue(lesson['completed'])
        self.assertEqual(lesson['quiz_attempt_count'], 2)
        self.assertEqual(lesson['quiz_best_score'], 100.0)

    def test_a_retake_keeps_the_best_score_even_if_the_new_one_is_lower(self):
        token = self._token()
        Quiz = self.env['college.quiz']
        Quiz.app_college_my_quiz_submit(token, self.lesson.id, answers={self.q1.id: self.q1_right.id, self.q2.id: self.q2_right.id})
        Quiz.app_college_my_quiz_submit(token, self.lesson.id, answers={self.q1.id: self.q1_wrong.id, self.q2.id: self.q2_wrong.id})
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertEqual(lesson['quiz_best_score'], 100.0)
        self.assertEqual(lesson['quiz_attempt_count'], 2)

    def test_an_unanswered_question_just_counts_as_wrong(self):
        token = self._token()
        result = self.env['college.quiz'].app_college_my_quiz_submit(token, self.lesson.id, answers={self.q1.id: self.q1_right.id})
        self.assertTrue(result['success'])
        self.assertEqual(result['score'], 50.0)

    def test_cannot_reach_a_quiz_for_a_course_not_enrolled_in(self):
        other_quiz = self.env['college.quiz'].create({'name': 'Other quiz'})
        other_q = self.env['college.quiz.question'].create({'quiz_id': other_quiz.id, 'text': 'Q'})
        self.env['college.quiz.option'].create({'question_id': other_q.id, 'text': 'A', 'is_correct': True})
        self.other_lesson.write({'content_type': 'quiz', 'quiz_id': other_quiz.id})
        token = self._token()
        result = self.env['college.quiz'].app_college_my_quiz(token, self.other_lesson.id)
        self.assertFalse(result['success'])
        submit = self.env['college.quiz'].app_college_my_quiz_submit(token, self.other_lesson.id, answers={})
        self.assertFalse(submit['success'])

    def test_cannot_reach_a_quiz_without_signing_in(self):
        result = self.env['college.quiz'].app_college_my_quiz('made-up-token', self.lesson.id)
        self.assertFalse(result['success'])

    def test_shuffled_order_does_not_change_grading(self):
        self.quiz.shuffle_questions = True
        token = self._token()
        result = self.env['college.quiz'].app_college_my_quiz_submit(token, self.lesson.id, answers={
            self.q1.id: self.q1_right.id, self.q2.id: self.q2_wrong.id,
        })
        self.assertEqual(result['score'], 50.0)
