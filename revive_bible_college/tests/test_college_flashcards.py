from odoo.tests.common import TransactionCase


class TestCollegeFlashcards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Old Testament Survey', 'program_id': cls.program.id})
        cls.other_course = cls.env['college.course'].create({'name': 'Other', 'program_id': cls.program.id})
        cls.module = cls.env['college.course.module'].create({'name': 'The Pentateuch', 'course_id': cls.course.id})

        cls.deck = cls.env['college.flashcard.deck'].create({'name': 'Books of the Pentateuch'})
        cls.card1 = cls.env['college.flashcard'].create({'deck_id': cls.deck.id, 'front': 'Genesis 1:1', 'back': 'In the beginning, God created the heavens and the earth.'})
        cls.card2 = cls.env['college.flashcard'].create({'deck_id': cls.deck.id, 'front': 'Exodus 20:2', 'back': 'I am the LORD your God, who brought you out of Egypt.'})

        cls.lesson = cls.env['college.course.content'].create({
            'name': 'Flashcards: The Pentateuch', 'module_id': cls.module.id, 'content_type': 'flashcards', 'deck_id': cls.deck.id,
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

    def test_student_sees_both_sides_of_every_card(self):
        token = self._token()
        result = self.env['college.flashcard.deck'].app_college_my_flashcards(token, self.lesson.id)
        self.assertTrue(result['success'], result)
        deck = result['deck']
        self.assertEqual(deck['name'], 'Books of the Pentateuch')
        self.assertEqual([c['front'] for c in deck['cards']], ['Genesis 1:1', 'Exodus 20:2'])
        self.assertTrue(deck['cards'][0]['back'].startswith('In the beginning'))
        self.assertFalse(deck['cards'][0]['known'])

    def test_marking_a_card_known_is_remembered(self):
        token = self._token()
        Deck = self.env['college.flashcard.deck']
        Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card1.id, True)
        deck = Deck.app_college_my_flashcards(token, self.lesson.id)['deck']
        known = {c['id']: c['known'] for c in deck['cards']}
        self.assertTrue(known[self.card1.id])
        self.assertFalse(known[self.card2.id])

    def test_the_deck_and_lesson_complete_only_once_every_card_is_known(self):
        token = self._token()
        Deck = self.env['college.flashcard.deck']
        first = Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card1.id, True)
        self.assertTrue(first['success'])
        self.assertFalse(first['deck_complete'])
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertFalse(lesson['completed'])
        self.assertEqual(lesson['flashcards_known'], 1)
        self.assertEqual(lesson['flashcards_total'], 2)

        second = Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card2.id, True)
        self.assertTrue(second['deck_complete'])
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertTrue(lesson['completed'])
        self.assertEqual(lesson['flashcards_known'], 2)

    def test_marking_a_card_unknown_again_does_not_undo_a_finished_lesson(self):
        token = self._token()
        Deck = self.env['college.flashcard.deck']
        Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card1.id, True)
        Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card2.id, True)
        Deck.app_college_my_flashcard_mark(token, self.lesson.id, self.card1.id, False)
        lesson = self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons'][0]
        self.assertTrue(lesson['completed'])
        self.assertEqual(lesson['flashcards_known'], 1)

    def test_cannot_reach_a_deck_for_a_course_not_enrolled_in(self):
        other_deck = self.env['college.flashcard.deck'].create({'name': 'Other deck'})
        other_card = self.env['college.flashcard'].create({'deck_id': other_deck.id, 'front': 'F', 'back': 'B'})
        self.other_lesson.write({'content_type': 'flashcards', 'deck_id': other_deck.id})
        token = self._token()
        Deck = self.env['college.flashcard.deck']
        self.assertFalse(Deck.app_college_my_flashcards(token, self.other_lesson.id)['success'])
        self.assertFalse(Deck.app_college_my_flashcard_mark(token, self.other_lesson.id, other_card.id, True)['success'])

    def test_cannot_mark_a_card_from_a_different_deck(self):
        other_deck = self.env['college.flashcard.deck'].create({'name': 'Other deck'})
        other_card = self.env['college.flashcard'].create({'deck_id': other_deck.id, 'front': 'F', 'back': 'B'})
        token = self._token()
        result = self.env['college.flashcard.deck'].app_college_my_flashcard_mark(token, self.lesson.id, other_card.id, True)
        self.assertFalse(result['success'])

    def test_cannot_reach_a_deck_without_signing_in(self):
        result = self.env['college.flashcard.deck'].app_college_my_flashcards('made-up-token', self.lesson.id)
        self.assertFalse(result['success'])
