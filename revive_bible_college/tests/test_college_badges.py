from odoo.tests.common import TransactionCase


class TestCollegeBadges(TransactionCase):

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

        cls.quiz = cls.env['college.quiz'].create({'name': 'The Exodus', 'pass_score': 60.0})
        cls.question = cls.env['college.quiz.question'].create({'quiz_id': cls.quiz.id, 'text': 'Who led Israel out of Egypt?'})
        cls.moses = cls.env['college.quiz.option'].create({'question_id': cls.question.id, 'text': 'Moses', 'is_correct': True})
        cls.joshua = cls.env['college.quiz.option'].create({'question_id': cls.question.id, 'text': 'Joshua', 'is_correct': False})
        cls.quiz_lesson = cls.env['college.course.content'].create({
            'name': 'Quiz: The Exodus', 'module_id': cls.module.id, 'content_type': 'quiz', 'quiz_id': cls.quiz.id,
        })

        cls.deck = cls.env['college.flashcard.deck'].create({'name': 'Books of the Pentateuch'})
        cls.card = cls.env['college.flashcard'].create({'deck_id': cls.deck.id, 'front': 'Genesis 1:1', 'back': 'In the beginning.'})
        cls.deck_lesson = cls.env['college.course.content'].create({
            'name': 'Flashcards: The Pentateuch', 'module_id': cls.module.id, 'content_type': 'flashcards', 'deck_id': cls.deck.id,
        })

        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create({'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

        cls.other_student = cls.env['college.student'].create(
            {'name': 'Ruth', 'email': 'ruth@example.com', 'program_id': cls.program.id})

    def _token(self, student):
        code = student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']

    def _badges(self, student):
        return {b['kind'] for b in student._app_self_detail()['badges']}

    def test_completing_the_first_lesson_awards_first_steps(self):
        token = self._token(self.student)
        self.env['college.lesson.progress'].app_college_my_progress_save(token, self.lesson1.id, completed=True)
        self.assertIn('first_lesson', self._badges(self.student))

    def test_completing_a_second_lesson_does_not_award_first_steps_again(self):
        token = self._token(self.student)
        Progress = self.env['college.lesson.progress']
        Progress.app_college_my_progress_save(token, self.lesson1.id, completed=True)
        Progress.app_college_my_progress_save(token, self.lesson2.id, completed=True)
        self.assertEqual(self.env['college.badge.award'].search_count([
            ('student_id', '=', self.student.id), ('kind', '=', 'first_lesson'),
        ]), 1)

    def test_passing_a_quiz_awards_quiz_whiz_and_a_perfect_score_awards_perfect_score(self):
        token = self._token(self.student)
        Quiz = self.env['college.quiz']
        submit = Quiz.app_college_my_quiz_submit(token, self.quiz_lesson.id, answers={str(self.question.id): self.moses.id})
        self.assertTrue(submit['passed'], submit)
        self.assertEqual(submit['score'], 100.0)
        badges = self._badges(self.student)
        self.assertIn('first_quiz_passed', badges)
        self.assertIn('perfect_quiz_score', badges)

    def test_a_non_perfect_pass_does_not_award_a_perfect_score(self):
        question2 = self.env['college.quiz.question'].create({'quiz_id': self.quiz.id, 'text': 'What sea did they cross?'})
        red_sea = self.env['college.quiz.option'].create({'question_id': question2.id, 'text': 'The Red Sea', 'is_correct': True})
        self.env['college.quiz.question'].create({'quiz_id': self.quiz.id, 'text': 'Who received the Ten Commandments?'})
        token = self._token(self.student)
        submit = self.env['college.quiz'].app_college_my_quiz_submit(
            token, self.quiz_lesson.id, answers={str(self.question.id): self.moses.id, str(question2.id): red_sea.id})
        self.assertTrue(submit['passed'], submit)
        self.assertLess(submit['score'], 100.0)
        badges = self._badges(self.student)
        self.assertIn('first_quiz_passed', badges)
        self.assertNotIn('perfect_quiz_score', badges)

    def test_mastering_a_flashcard_deck_awards_card_master(self):
        token = self._token(self.student)
        mark = self.env['college.flashcard.deck'].app_college_my_flashcard_mark(token, self.deck_lesson.id, self.card.id, True)
        self.assertTrue(mark['deck_complete'], mark)
        self.assertIn('first_deck_mastered', self._badges(self.student))

    def test_completing_every_lesson_awards_course_complete_only_once_all_are_done(self):
        token = self._token(self.student)
        Progress = self.env['college.lesson.progress']
        Progress.app_college_my_progress_save(token, self.lesson1.id, completed=True)
        Progress.app_college_my_progress_save(token, self.lesson2.id, completed=True)
        self.assertNotIn('first_course_complete', self._badges(self.student))

        self.env['college.quiz'].app_college_my_quiz_submit(token, self.quiz_lesson.id, answers={str(self.question.id): self.moses.id})
        self.assertNotIn('first_course_complete', self._badges(self.student))

        self.env['college.flashcard.deck'].app_college_my_flashcard_mark(token, self.deck_lesson.id, self.card.id, True)
        self.assertIn('first_course_complete', self._badges(self.student))

    def test_unmarking_a_lesson_does_not_take_back_an_awarded_badge(self):
        token = self._token(self.student)
        Progress = self.env['college.lesson.progress']
        Progress.app_college_my_progress_save(token, self.lesson1.id, completed=True)
        self.assertIn('first_lesson', self._badges(self.student))
        Progress.app_college_my_progress_save(token, self.lesson1.id, completed=False)
        self.assertIn('first_lesson', self._badges(self.student))

    def test_badges_are_specific_to_each_student(self):
        token = self._token(self.student)
        self.env['college.lesson.progress'].app_college_my_progress_save(token, self.lesson1.id, completed=True)
        self.assertIn('first_lesson', self._badges(self.student))
        self.assertEqual(self._badges(self.other_student), set())
