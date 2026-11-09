import json
import random
import re

from odoo import api, fields, models

from .college_app_api import token_student

QUESTION_TYPES = [
    ('single', 'Pick one answer'),
    ('true_false', 'True / False'),
    ('multiple', 'Choose all that apply'),
    ('fill_blank', 'Fill in the blank'),
    ('matching', 'Matching'),
    ('ordering', 'Put in order'),
]
_NOT_WORD = re.compile(r'[^\w\s]', re.UNICODE)


def normalize_answer(text):
    """For comparing typed answers: ignores capitals, punctuation and extra
    spaces (but not spelling)."""
    return ' '.join(_NOT_WORD.sub('', str(text or '')).lower().split())


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CollegeQuiz(models.Model):
    """A reusable bank of multiple-choice questions. Attach one to a lesson
    by setting that lesson's content_type to 'quiz' and quiz_id to this
    record (see college_course_content.py)."""
    _name = 'college.quiz'
    _description = 'Bible College Quiz'
    _order = 'name'

    name = fields.Char(translate=True, required=True)
    description = fields.Text(translate=True)
    pass_score = fields.Float(string='Passing Score (%)', default=60.0)
    shuffle_questions = fields.Boolean(default=False, help='Show each student the questions in a different order.')
    shuffle_answers = fields.Boolean(
        default=False, help='Show the answers of each question in a different order every time, so students '
                            'learn the answer rather than its place. "Put in order" questions are always shuffled.')
    question_ids = fields.One2many('college.quiz.question', 'quiz_id', string='Questions')
    question_count = fields.Integer(compute='_compute_question_count')
    attempt_count = fields.Integer(compute='_compute_attempt_count')

    def _compute_question_count(self):
        for quiz in self:
            quiz.question_count = len(quiz.question_ids)

    def _compute_attempt_count(self):
        for quiz in self:
            quiz.attempt_count = self.env['college.quiz.attempt'].search_count([('quiz_id', '=', quiz.id)])

    def action_view_questions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Questions',
            'res_model': 'college.quiz.question',
            'view_mode': 'list,form',
            'domain': [('quiz_id', '=', self.id)],
            'context': {'default_quiz_id': self.id},
        }

    def action_view_attempts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attempts',
            'res_model': 'college.quiz.attempt',
            'view_mode': 'list,form',
            'domain': [('quiz_id', '=', self.id)],
        }

    # ── App API (student's own view, token-only) ──────────────────
    # Quizzes are new in 19.0.1.13.0, so there is no legacy code+email
    # path to support here, unlike the older content/assignment endpoints.

    def _enrolled_quiz_content(self, student, content_id):
        """The college.course.content row for this quiz, if the student is
        enrolled in its course, else an empty recordset."""
        content = self.env['college.course.content'].sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.content_type != 'quiz' or not content.quiz_id:
            return self.env['college.course.content']
        if content.course_id.id not in enrolled_course_ids:
            return self.env['college.course.content']
        return content

    @api.model
    def app_college_my_quiz(self, token, content_id):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self._enrolled_quiz_content(student, content_id)
        if not content:
            return {'success': False, 'error': 'Not found'}
        quiz = content.quiz_id.sudo()
        questions = list(quiz.question_ids)
        if quiz.shuffle_questions:
            random.shuffle(questions)
        attempts = self.env['college.quiz.attempt'].sudo().search([
            ('quiz_id', '=', quiz.id), ('student_id', '=', student.id),
        ])
        return {
            'success': True,
            'quiz': {
                'id': quiz.id, 'name': quiz.name, 'description': quiz.description or '',
                'pass_score': quiz.pass_score,
                'best_score': max(attempts.mapped('score')) if attempts else None,
                'attempt_count': len(attempts),
                'questions': [q._app_payload(quiz.shuffle_answers) for q in questions],
            },
        }

    @api.model
    def app_college_my_quiz_submit(self, token, content_id, answers=None):
        """answers: {question_id: option_id}. Graded here, never trusting a
        client-computed score. Marks the lesson complete when the student
        passes — matches how a video completes itself when watched through."""
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self._enrolled_quiz_content(student, content_id)
        if not content:
            return {'success': False, 'error': 'Not found'}
        quiz = content.quiz_id.sudo()
        answers = {_as_int(k): v for k, v in (answers or {}).items()}
        questions = quiz.question_ids
        if not questions:
            return {'success': False, 'error': 'This quiz has no questions yet'}
        total_credit = 0.0
        answer_vals = []
        results = []
        for question in questions:
            credit, chosen, correct = question._grade(answers.get(question.id))
            total_credit += credit
            is_correct = credit >= 0.999
            single_option = chosen if question.question_type == 'single' and chosen else False
            answer_vals.append((0, 0, {
                'question_id': question.id, 'option_id': single_option, 'is_correct': is_correct,
                'credit': credit, 'answer_text': json.dumps(chosen) if chosen not in (None, '', [], {}) else False,
            }))
            result = {
                'question_id': question.id, 'question_type': question.question_type,
                'is_correct': is_correct, 'credit': round(credit, 3), 'explanation': question.explanation or '',
                'chosen': chosen, 'correct': correct,
            }
            if question.question_type == 'single':
                # The original single-answer shape, which older app builds read.
                result.update({'chosen_option_id': chosen or None, 'correct_option_id': correct or None})
            results.append(result)
        score = round(total_credit / len(questions) * 100, 1)
        passed = score >= quiz.pass_score
        attempt = self.env['college.quiz.attempt'].sudo().create({
            'quiz_id': quiz.id, 'student_id': student.id, 'score': score, 'passed': passed, 'answer_ids': answer_vals,
        })
        if passed:
            Progress = self.env['college.lesson.progress'].sudo()
            progress = Progress.search([('student_id', '=', student.id), ('content_id', '=', content.id)], limit=1)
            if progress:
                progress.write({'completed': True, 'completed_date': fields.Datetime.now()})
            else:
                Progress.create({'student_id': student.id, 'content_id': content.id, 'completed': True,
                                 'completed_date': fields.Datetime.now()})
            Badge = self.env['college.badge.award'].sudo()
            Badge._award(student, 'first_quiz_passed')
            if score >= 100.0:
                Badge._award(student, 'perfect_quiz_score')
            Badge._check_lesson_complete(student, content)
        return {
            'success': True, 'attempt_id': attempt.id, 'score': score, 'passed': passed,
            'pass_score': quiz.pass_score, 'results': results,
        }


class CollegeQuizQuestion(models.Model):
    _name = 'college.quiz.question'
    _description = 'Bible College Quiz Question'
    _order = 'quiz_id, sequence, id'
    _rec_name = 'text'

    quiz_id = fields.Many2one('college.quiz', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    question_type = fields.Selection(QUESTION_TYPES, string='Type', default='single', required=True)
    text = fields.Text(translate=True, required=True, string='Question')
    image = fields.Image(max_width=1600, max_height=1600, help='Optional, e.g. a map. Shown above the question.')
    explanation = fields.Text(translate=True, help='Shown to the student after they answer, whether they were right or wrong.')
    option_ids = fields.One2many('college.quiz.option', 'question_id', string='Options')
    tf_answer = fields.Selection([('true', 'True'), ('false', 'False')], string='The statement is')
    accepted_answers = fields.Text(translate=True,
        help='One accepted answer per line. Capitals, punctuation and extra spaces are ignored; spelling is not.')
    setup_problem = fields.Char(compute='_compute_setup_problem')
    has_correct_option = fields.Boolean(compute='_compute_setup_problem',
                                        help='False while the question is not yet answerable (see the warning).')

    @api.depends('question_type', 'option_ids.is_correct', 'option_ids.match_text', 'tf_answer', 'accepted_answers')
    def _compute_setup_problem(self):
        for q in self:
            kind, options = q.question_type, q.option_ids
            problem = ''
            if kind in ('single', 'multiple') and not any(options.mapped('is_correct')):
                problem = 'No option is marked correct. A student can never answer this one right.'
            elif kind == 'true_false' and not q.tf_answer:
                problem = 'Choose whether the statement is True or False.'
            elif kind == 'fill_blank' and not q._accepted():
                problem = 'Add at least one accepted answer.'
            elif kind == 'matching' and len(options.filtered('match_text')) < 2:
                problem = 'Add at least two pairs (an item and what it matches).'
            elif kind == 'ordering' and len(options) < 2:
                problem = 'Add at least two items, in the correct order.'
            q.setup_problem = problem
            q.has_correct_option = not problem

    def _accepted(self):
        return [line.strip() for line in (self.accepted_answers or '').splitlines() if line.strip()]

    def _app_payload(self, shuffle_answers):
        """What the app needs to ask this question. Never says which answer
        is right, what matches what, or the correct order."""
        self.ensure_one()
        kind = self.question_type
        items = [{'id': o.id, 'text': o.text} for o in self.option_ids]
        payload = {'id': self.id, 'type': kind, 'text': self.text, 'has_image': bool(self.image), 'options': []}
        if kind in ('single', 'multiple'):
            if shuffle_answers:
                random.shuffle(items)
            payload['options'] = items
        elif kind == 'matching':
            pairs = [{'id': o.id, 'text': o.text} for o in self.option_ids if o.match_text]
            if shuffle_answers:
                random.shuffle(pairs)
            choices = sorted({o.match_text.strip() for o in self.option_ids if o.match_text})
            random.shuffle(choices)
            payload.update({'options': pairs, 'choices': choices})
        elif kind == 'ordering':
            # Always shuffled, and never handed over already in order.
            shuffled = items[:]
            for _attempt in range(10):
                random.shuffle(shuffled)
                if len(shuffled) < 2 or shuffled != items:
                    break
            payload['options'] = shuffled
        return payload

    def _grade(self, answer):
        """(credit from 0 to 1, the answer as understood, the right answer)."""
        self.ensure_one()
        kind, options = self.question_type, self.option_ids
        if kind == 'single':
            chosen = _as_int(answer)
            correct = options.filtered('is_correct')
            chosen = chosen if chosen in options.ids else None
            return (1.0 if chosen in correct.ids else 0.0), chosen, correct[:1].id or None
        if kind == 'true_false':
            chosen = answer if isinstance(answer, bool) else {'true': True, 'false': False}.get(str(answer).lower())
            correct = {'true': True, 'false': False}.get(self.tf_answer)
            return (1.0 if chosen is not None and chosen == correct else 0.0), chosen, correct
        if kind == 'multiple':
            picked = answer if isinstance(answer, list) else []
            chosen = sorted({i for i in (_as_int(a) for a in picked) if i in options.ids})
            correct = options.filtered('is_correct').ids
            if not correct:
                return 0.0, chosen, correct
            right = len(set(chosen) & set(correct))
            wrong = len(set(chosen) - set(correct))
            # Partial credit, with a wrong pick cancelling a right one.
            return max(0.0, (right - wrong) / len(correct)), chosen, correct
        if kind == 'fill_blank':
            chosen = str(answer or '').strip()
            accepted = self._accepted()
            ok = bool(chosen) and normalize_answer(chosen) in {normalize_answer(a) for a in accepted}
            return (1.0 if ok else 0.0), chosen, accepted[0] if accepted else ''
        if kind == 'matching':
            pairs = options.filtered('match_text')
            given = answer if isinstance(answer, dict) else {}
            chosen = {str(o.id): str(given.get(str(o.id), given.get(o.id, '')) or '') for o in pairs}
            correct = {str(o.id): o.match_text.strip() for o in pairs}
            if not pairs:
                return 0.0, chosen, correct
            right = sum(1 for key, text in correct.items() if normalize_answer(chosen[key]) == normalize_answer(text))
            return right / len(pairs), chosen, correct
        if kind == 'ordering':
            correct = options.ids  # options are kept in their correct order (sequence)
            picked = answer if isinstance(answer, list) else []
            chosen = [i for i in (_as_int(a) for a in picked) if i in correct]
            if not correct or sorted(chosen) != sorted(correct):
                return 0.0, chosen, correct
            return sum(1 for a, b in zip(chosen, correct) if a == b) / len(correct), chosen, correct
        return 0.0, None, None


class CollegeQuizOption(models.Model):
    _name = 'college.quiz.option'
    _description = 'Bible College Quiz Option'
    _order = 'question_id, sequence, id'
    _rec_name = 'text'

    question_id = fields.Many2one('college.quiz.question', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    text = fields.Char(translate=True, required=True)
    is_correct = fields.Boolean(default=False)
    # Matching questions only: what this item is matched with.
    match_text = fields.Char(translate=True, string='Matches')


class CollegeQuizAttempt(models.Model):
    """One graded attempt. A student may attempt a quiz more than once —
    each attempt is kept, so staff can see improvement over time and the
    app can show the best score."""
    _name = 'college.quiz.attempt'
    _description = 'Bible College Quiz Attempt'
    _order = 'id desc'
    _rec_name = 'student_id'

    quiz_id = fields.Many2one('college.quiz', required=True, ondelete='cascade')
    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    score = fields.Float(string='Score (%)')
    passed = fields.Boolean()
    submitted_date = fields.Datetime(default=fields.Datetime.now)
    answer_ids = fields.One2many('college.quiz.answer', 'attempt_id', string='Answers')


class CollegeQuizAnswer(models.Model):
    """One question's answer within one attempt. Keeps whether it was
    correct at the time, so a later edit to the question doesn't rewrite
    history."""
    _name = 'college.quiz.answer'
    _description = 'Bible College Quiz Answer'
    _order = 'id'

    attempt_id = fields.Many2one('college.quiz.attempt', required=True, ondelete='cascade')
    question_id = fields.Many2one('college.quiz.question', required=True, ondelete='cascade')
    option_id = fields.Many2one('college.quiz.option')
    is_correct = fields.Boolean()
    # Partial credit for "choose all", matching and ordering (0 to 1).
    credit = fields.Float(digits=(3, 2))
    answer_text = fields.Text(string='Answer given')
