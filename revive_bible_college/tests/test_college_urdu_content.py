from odoo.tests.common import TransactionCase

from .test_college_quiz_types import _QuizSetup

UR = 'ur_PK'


class TestCollegeUrduContent(_QuizSetup, TransactionCase):
    """Staff can give any piece of course content an Urdu version; the app
    asks for it with lang=ur_PK and gets English where none was written."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_quiz()

    def setUp(self):
        super().setUp()
        self.token = self._token(self.student)

    def ur(self, record):
        return record.with_context(lang=UR)

    def test_urdu_is_available_right_to_left(self):
        urdu = self.env['res.lang'].search([('code', '=', UR)])
        self.assertTrue(urdu.active)
        self.assertEqual(urdu.direction, 'rtl')
        # Running it again (every upgrade does) changes nothing.
        self.env['college.course']._ensure_urdu_language()
        self.assertEqual(self.env['res.lang'].with_context(active_test=False).search_count([('code', '=', UR)]), 1)

    def test_lessons_come_in_urdu_with_english_where_none_was_written(self):
        self.ur(self.course).name = 'عہدِ عتیق کا جائزہ'
        self.ur(self.youtube).write({'name': 'تعارف', 'chapters_text': '0:00 آغاز\n4:30 موسیٰ اور فرعون'})
        Student = self.env['college.student']
        english = Student.app_college_my_studies(self.token)['student']['enrollments'][0]
        urdu = Student.with_context(lang=UR).app_college_my_studies(self.token)['student']['enrollments'][0]
        self.assertEqual(english['course_name'], 'Old Testament Survey')
        self.assertEqual(urdu['course_name'], 'عہدِ عتیق کا جائزہ')
        by_id = {l['id']: l for l in urdu['modules'][0]['lessons']}
        self.assertEqual(by_id[self.youtube.id]['name'], 'تعارف')
        self.assertEqual(by_id[self.youtube.id]['chapters'][1], {'seconds': 270, 'title': 'موسیٰ اور فرعون'})
        self.assertEqual(by_id[self.lesson.id]['name'], 'The Exodus')  # no Urdu written: English
        self.assertEqual(urdu['modules'][0]['name'], 'The Pentateuch')

    def test_quiz_questions_and_answers_come_in_urdu(self):
        self.ur(self.tf).write({'text': 'موسیٰ نے پیدایش کی کتاب لکھی۔', 'explanation': 'روایت کے مطابق۔'})
        romans = self.match.option_ids.filtered(lambda o: o.text == 'Romans')
        self.ur(romans).write({'text': 'رومیوں', 'match_text': 'پولُس'})
        quiz = self.env['college.quiz'].with_context(lang=UR).app_college_my_quiz(self.token, self.quiz_lesson.id)['quiz']
        questions = {q['id']: q for q in quiz['questions']}
        self.assertEqual(questions[self.tf.id]['text'], 'موسیٰ نے پیدایش کی کتاب لکھی۔')
        match = questions[self.match.id]
        self.assertIn('رومیوں', [o['text'] for o in match['options']])
        self.assertIn('پولُس', match['choices'])
        self.assertIn('Paul', match['choices'])  # Galatians -> Paul has no Urdu yet

    def test_answers_typed_or_matched_in_urdu_are_marked_in_urdu(self):
        self.ur(self.fill).accepted_answers = 'آسمان اور زمین\nزمین'
        romans = self.match.option_ids.filtered(lambda o: o.text == 'Romans')
        self.ur(romans).match_text = 'پولُس'
        Quiz = self.env['college.quiz']
        answers = {
            self.fill.id: 'زمین',
            self.match.id: {str(romans.id): 'پولُس'},
        }
        urdu = {r['question_id']: r for r in Quiz.with_context(lang=UR).app_college_my_quiz_submit(
            self.token, self.quiz_lesson.id, answers=answers)['results']}
        self.assertTrue(urdu[self.fill.id]['is_correct'])
        self.assertEqual(urdu[self.fill.id]['correct'], 'آسمان اور زمین')
        self.assertEqual(urdu[self.match.id]['correct'][str(romans.id)], 'پولُس')
        self.assertEqual(urdu[self.match.id]['credit'], 0.25)  # one of four pairs
        # The English answers still work for a student using English.
        english = {r['question_id']: r for r in Quiz.app_college_my_quiz_submit(
            self.token, self.quiz_lesson.id, answers={self.fill.id: 'heaven and earth'})['results']}
        self.assertTrue(english[self.fill.id]['is_correct'])

    def test_flashcards_and_video_questions_come_in_urdu(self):
        deck = self.env['college.flashcard.deck'].create({'name': 'Verses', 'card_ids': [(0, 0, {'front': 'Genesis 1:1', 'back': 'In the beginning...'})]})
        lesson = self.env['college.course.content'].create({'name': 'Cards', 'module_id': self.module.id, 'content_type': 'flashcards', 'deck_id': deck.id})
        self.ur(deck.card_ids).write({'front': 'پیدایش 1:1', 'back': 'ابتدا میں اللہ نے آسمان اور زمین کو بنایا۔'})
        cards = self.env['college.flashcard.deck'].with_context(lang=UR).app_college_my_flashcards(self.token, lesson.id)['deck']['cards']
        self.assertEqual(cards[0]['front'], 'پیدایش 1:1')
        question = self.env['college.video.question'].create({
            'content_id': self.youtube.id, 'pause_time': '0:20', 'text': 'Who spoke from the bush?',
            'option_ids': [(0, 0, {'text': 'God', 'is_correct': True}), (0, 0, {'text': 'Aaron'})]})
        self.ur(question).text = 'جھاڑی میں سے کس نے کلام کیا؟'
        self.ur(question.option_ids[0]).text = 'اللہ'
        lessons = self.env['college.student'].with_context(lang=UR).app_college_my_studies(self.token)['student']['enrollments'][0]['modules'][0]['lessons']
        payload = {l['id']: l for l in lessons}[self.youtube.id]['video_questions'][0]
        self.assertEqual(payload['text'], 'جھاڑی میں سے کس نے کلام کیا؟')
        self.assertEqual([o['text'] for o in payload['options']], ['اللہ', 'Aaron'])
