import base64
import json

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from odoo.addons.revive_bible_college.models.college_quiz import normalize_answer

from .test_college_video import _VideoSetup

# A 1x1 PNG.
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')


class _QuizSetup(_VideoSetup):

    @classmethod
    def _make_quiz(cls):
        cls._make_course()
        cls.quiz = cls.env['college.quiz'].create({'name': 'Pentateuch review', 'pass_score': 60.0})
        cls.quiz_lesson = cls.env['college.course.content'].create({
            'name': 'Quiz', 'module_id': cls.module.id, 'content_type': 'quiz', 'quiz_id': cls.quiz.id,
        })
        Q = cls.env['college.quiz.question']
        cls.tf = Q.create({'quiz_id': cls.quiz.id, 'sequence': 1, 'question_type': 'true_false',
                           'text': 'Moses wrote Genesis.', 'tf_answer': 'true'})
        cls.multi = Q.create({'quiz_id': cls.quiz.id, 'sequence': 2, 'question_type': 'multiple',
                              'text': 'Which are Gospels?', 'option_ids': [
                                  (0, 0, {'text': 'Matthew', 'is_correct': True}),
                                  (0, 0, {'text': 'Mark', 'is_correct': True}),
                                  (0, 0, {'text': 'Acts'}),
                                  (0, 0, {'text': 'John', 'is_correct': True}),
                              ]})
        cls.fill = Q.create({'quiz_id': cls.quiz.id, 'sequence': 3, 'question_type': 'fill_blank',
                             'text': 'In the beginning God created the ___.',
                             'accepted_answers': 'heavens and the earth\nheaven and earth\n'})
        cls.match = Q.create({'quiz_id': cls.quiz.id, 'sequence': 4, 'question_type': 'matching',
                              'text': 'Match each book to its author.', 'option_ids': [
                                  (0, 0, {'text': 'Romans', 'match_text': 'Paul'}),
                                  (0, 0, {'text': 'Revelation', 'match_text': 'John'}),
                                  (0, 0, {'text': 'Galatians', 'match_text': 'Paul'}),
                                  (0, 0, {'text': '1 Peter', 'match_text': 'Peter'}),
                              ]})
        cls.order = Q.create({'quiz_id': cls.quiz.id, 'sequence': 5, 'question_type': 'ordering',
                              'text': 'Put these in order.', 'option_ids': [
                                  (0, 0, {'text': 'Creation', 'sequence': 1}),
                                  (0, 0, {'text': 'Flood', 'sequence': 2}),
                                  (0, 0, {'text': 'Abraham', 'sequence': 3}),
                                  (0, 0, {'text': 'Exodus', 'sequence': 4}),
                              ]})


class TestQuizTypes(_QuizSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_quiz()

    def setUp(self):
        super().setUp()
        self.token = self._token(self.student)
        self.Quiz = self.env['college.quiz']

    def opt(self, question, text):
        return question.option_ids.filtered(lambda o: o.text == text).id

    def submit(self, answers):
        return self.Quiz.app_college_my_quiz_submit(self.token, self.quiz_lesson.id, answers=answers)

    def by_question(self, result):
        return {r['question_id']: r for r in result['results']}

    def perfect(self):
        return {
            self.tf.id: True,
            self.multi.id: [self.opt(self.multi, t) for t in ('Matthew', 'Mark', 'John')],
            self.fill.id: 'Heaven and Earth!',
            self.match.id: {str(self.opt(self.match, 'Romans')): 'Paul', str(self.opt(self.match, 'Revelation')): 'John',
                            str(self.opt(self.match, 'Galatians')): 'Paul', str(self.opt(self.match, '1 Peter')): 'Peter'},
            self.order.id: self.order.option_ids.ids,
        }

    def test_typed_answers_ignore_capitals_punctuation_and_spaces_but_not_spelling(self):
        self.assertEqual(normalize_answer('  Heaven, and   EARTH! '), 'heaven and earth')
        self.assertEqual(self.fill._grade('heavens and the earth.')[0], 1.0)
        self.assertEqual(self.fill._grade('heven and earth')[0], 0.0)
        self.assertEqual(self.fill._grade('')[0], 0.0)

    def test_the_app_never_gets_the_answers(self):
        quiz = self.Quiz.app_college_my_quiz(self.token, self.quiz_lesson.id)['quiz']
        questions = {q['id']: q for q in quiz['questions']}
        self.assertEqual(questions[self.tf.id]['type'], 'true_false')
        self.assertEqual(questions[self.tf.id]['options'], [])
        self.assertEqual(questions[self.fill.id]['options'], [])
        blob = json.dumps(quiz)
        for secret in ('is_correct', 'match_text', 'accepted', 'heaven', 'tf_answer'):
            self.assertNotIn(secret, blob)
        match = questions[self.match.id]
        self.assertEqual(sorted(match['choices']), ['John', 'Paul', 'Peter'])  # each answer listed once
        self.assertEqual(len(match['options']), 4)
        self.assertEqual({o['text'] for o in questions[self.multi.id]['options']}, {'Matthew', 'Mark', 'Acts', 'John'})

    def test_put_in_order_is_never_handed_over_already_in_order(self):
        for _ in range(15):
            payload = self.order._app_payload(False)
            self.assertNotEqual([o['id'] for o in payload['options']], self.order.option_ids.ids)
            self.assertEqual(sorted(o['id'] for o in payload['options']), sorted(self.order.option_ids.ids))

    def test_a_perfect_quiz_scores_100(self):
        result = self.submit(self.perfect())
        self.assertEqual(result['score'], 100.0)
        self.assertTrue(result['passed'])
        self.assertTrue(all(r['is_correct'] for r in result['results']))

    def test_choose_all_gives_partial_marks_and_a_wrong_pick_cancels_a_right_one(self):
        m = self.multi
        self.assertAlmostEqual(m._grade([self.opt(m, 'Matthew'), self.opt(m, 'Mark')])[0], 2 / 3)
        self.assertAlmostEqual(m._grade([self.opt(m, 'Matthew'), self.opt(m, 'Mark'), self.opt(m, 'Acts')])[0], 1 / 3)
        self.assertEqual(m._grade([self.opt(m, 'Acts')])[0], 0.0)
        everything = m.option_ids.ids
        self.assertAlmostEqual(m._grade(everything)[0], 2 / 3)  # ticking everything isn't a free pass
        self.assertEqual(m._grade([])[0], 0.0)
        self.assertEqual(m._grade('not a list')[0], 0.0)

    def test_matching_gives_a_mark_per_pair(self):
        m = self.match
        answer = {str(self.opt(m, 'Romans')): 'paul', str(self.opt(m, 'Revelation')): 'Paul',
                  str(self.opt(m, 'Galatians')): 'Paul'}  # 1 Peter left blank
        credit, chosen, correct = m._grade(answer)
        self.assertEqual(credit, 0.5)
        self.assertEqual(chosen[str(self.opt(m, '1 Peter'))], '')
        self.assertEqual(correct[str(self.opt(m, 'Revelation'))], 'John')

    def test_ordering_gives_a_mark_per_item_in_the_right_place(self):
        creation, flood, abraham, exodus = self.order.option_ids.ids
        self.assertEqual(self.order._grade([creation, flood, exodus, abraham])[0], 0.5)
        self.assertEqual(self.order._grade([exodus, abraham, flood, creation])[0], 0.0)
        self.assertEqual(self.order._grade([creation, flood])[0], 0.0)  # incomplete
        self.assertEqual(self.order._grade([creation, creation, flood, abraham])[0], 0.0)  # tampered

    def test_true_false_accepts_true_or_the_word(self):
        self.assertEqual(self.tf._grade(True)[0], 1.0)
        self.assertEqual(self.tf._grade('true')[0], 1.0)
        self.assertEqual(self.tf._grade(False)[0], 0.0)
        self.assertEqual(self.tf._grade(None)[0], 0.0)

    def test_the_score_adds_up_partial_marks_and_results_show_the_right_answers(self):
        answers = self.perfect()
        answers[self.multi.id] = [self.opt(self.multi, 'Matthew')]  # 1/3
        answers[self.fill.id] = 'heven and earth'  # 0
        result = self.submit(answers)
        # (1 + 1/3 + 0 + 1 + 1) / 5
        self.assertEqual(result['score'], 66.7)
        self.assertTrue(result['passed'])
        r = self.by_question(result)
        self.assertFalse(r[self.multi.id]['is_correct'])
        self.assertEqual(r[self.multi.id]['credit'], 0.333)
        self.assertEqual(sorted(r[self.multi.id]['correct']),
                         sorted(self.opt(self.multi, t) for t in ('Matthew', 'Mark', 'John')))
        self.assertEqual(r[self.fill.id]['correct'], 'heavens and the earth')
        self.assertEqual(r[self.fill.id]['chosen'], 'heven and earth')
        self.assertEqual(r[self.tf.id]['correct'], True)
        self.assertEqual(r[self.order.id]['correct'], self.order.option_ids.ids)
        attempt = self.env['college.quiz.attempt'].search([('student_id', '=', self.student.id)])
        multi_answer = attempt.answer_ids.filtered(lambda a: a.question_id == self.multi)
        self.assertAlmostEqual(multi_answer.credit, 0.33, places=2)
        self.assertEqual(json.loads(multi_answer.answer_text), [self.opt(self.multi, 'Matthew')])

    def test_missing_answers_score_zero_without_errors(self):
        result = self.submit({})
        self.assertEqual(result['score'], 0.0)
        self.assertFalse(result['passed'])

    def test_each_type_warns_until_it_can_be_answered(self):
        Q = self.env['college.quiz.question']
        cases = [
            ({'question_type': 'true_false'}, 'True or False'),
            ({'question_type': 'fill_blank', 'accepted_answers': '\n  \n'}, 'accepted answer'),
            ({'question_type': 'matching', 'option_ids': [(0, 0, {'text': 'Romans', 'match_text': 'Paul'})]}, 'two pairs'),
            ({'question_type': 'ordering', 'option_ids': [(0, 0, {'text': 'Only one'})]}, 'two items'),
            ({'question_type': 'multiple', 'option_ids': [(0, 0, {'text': 'A'})]}, 'marked correct'),
        ]
        for vals, words in cases:
            question = Q.create({'quiz_id': self.quiz.id, 'text': 'Q', **vals})
            self.assertFalse(question.has_correct_option, vals)
            self.assertIn(words, question.setup_problem)
        for question in (self.tf, self.multi, self.fill, self.match, self.order):
            self.assertTrue(question.has_correct_option, question.question_type)

    def test_shuffle_answers_keeps_every_answer(self):
        self.quiz.shuffle_answers = True
        seen_orders = set()
        for _ in range(20):
            options = self.multi._app_payload(True)['options']
            self.assertEqual(len(options), 4)
            seen_orders.add(tuple(o['id'] for o in options))
        self.assertGreater(len(seen_orders), 1)

    def test_existing_pick_one_questions_still_work_the_old_way(self):
        old = self.env['college.quiz.question'].create({
            'quiz_id': self.quiz.id, 'text': 'Who led Israel?',
            'option_ids': [(0, 0, {'text': 'Moses', 'is_correct': True}), (0, 0, {'text': 'Joshua'})],
        })
        self.assertEqual(old.question_type, 'single')
        moses = self.opt(old, 'Moses')
        # An older app build sends {question id: option id} and reads these keys.
        result = self.submit({str(old.id): moses})
        r = self.by_question(result)[old.id]
        self.assertTrue(r['is_correct'])
        self.assertEqual(r['chosen_option_id'], moses)
        self.assertEqual(r['correct_option_id'], moses)


@tagged('post_install', '-at_install')
class TestQuizImageHttp(_QuizSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_quiz()
        cls.tf.image = base64.b64encode(PNG)

    def test_a_question_picture_reaches_enrolled_students_only(self):
        token = self._token(self.student)
        url = '/college/quiz/question/%d/image' % self.tf.id
        response = self.url_open(url, headers={'X-College-Token': token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['Content-Type'].startswith('image/'))
        self.assertEqual(self.url_open(url).status_code, 404)
        payload = self.env['college.quiz'].app_college_my_quiz(token, self.quiz_lesson.id)['quiz']
        self.assertTrue({q['id']: q for q in payload['questions']}[self.tf.id]['has_image'])

        other = self.env['college.student'].create({'name': 'Ruth', 'email': 'r@example.com', 'program_id': self.program.id})
        self.assertEqual(self.url_open(url, headers={'X-College-Token': self._token(other)}).status_code, 404)
        no_image = '/college/quiz/question/%d/image' % self.fill.id
        self.assertEqual(self.url_open(no_image, headers={'X-College-Token': token}).status_code, 404)
