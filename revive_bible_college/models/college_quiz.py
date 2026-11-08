import random

from odoo import api, fields, models

from .college_app_api import token_student


class CollegeQuiz(models.Model):
    """A reusable bank of multiple-choice questions. Attach one to a lesson
    by setting that lesson's content_type to 'quiz' and quiz_id to this
    record (see college_course_content.py)."""
    _name = 'college.quiz'
    _description = 'Bible College Quiz'
    _order = 'name'

    name = fields.Char(required=True)
    description = fields.Text()
    pass_score = fields.Float(string='Passing Score (%)', default=60.0)
    shuffle_questions = fields.Boolean(default=False, help='Show each student the questions in a different order.')
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
                'questions': [{
                    'id': q.id, 'text': q.text,
                    'options': [{'id': o.id, 'text': o.text} for o in q.option_ids],
                } for q in questions],
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
        answers = {int(k): v for k, v in (answers or {}).items()}
        questions = quiz.question_ids
        if not questions:
            return {'success': False, 'error': 'This quiz has no questions yet'}
        Option = self.env['college.quiz.option'].sudo()
        correct_count = 0
        answer_vals = []
        results = []
        for question in questions:
            chosen_id = answers.get(question.id)
            chosen = Option.browse(chosen_id) if chosen_id else Option
            correct = question.option_ids.filtered('is_correct')[:1]
            is_correct = bool(chosen) and chosen.id in question.option_ids.filtered('is_correct').ids
            if is_correct:
                correct_count += 1
            answer_vals.append((0, 0, {'question_id': question.id, 'option_id': chosen.id or False, 'is_correct': is_correct}))
            results.append({
                'question_id': question.id, 'chosen_option_id': chosen.id or None,
                'correct_option_id': correct.id if correct else None,
                'is_correct': is_correct, 'explanation': question.explanation or '',
            })
        score = round(correct_count / len(questions) * 100, 1)
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
        return {
            'success': True, 'attempt_id': attempt.id, 'score': score, 'passed': passed,
            'pass_score': quiz.pass_score, 'results': results,
        }


class CollegeQuizQuestion(models.Model):
    _name = 'college.quiz.question'
    _description = 'Bible College Quiz Question'
    _order = 'quiz_id, sequence, id'

    quiz_id = fields.Many2one('college.quiz', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    text = fields.Text(required=True, string='Question')
    explanation = fields.Text(help='Shown to the student after they answer, whether they were right or wrong.')
    option_ids = fields.One2many('college.quiz.option', 'question_id', string='Options')
    has_correct_option = fields.Boolean(compute='_compute_has_correct_option',
                                         help='A question with no correct option marked can never be answered right.')

    @api.depends('option_ids.is_correct')
    def _compute_has_correct_option(self):
        for question in self:
            question.has_correct_option = any(question.option_ids.mapped('is_correct'))


class CollegeQuizOption(models.Model):
    _name = 'college.quiz.option'
    _description = 'Bible College Quiz Option'
    _order = 'question_id, sequence, id'
    _rec_name = 'text'

    question_id = fields.Many2one('college.quiz.question', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    text = fields.Char(required=True)
    is_correct = fields.Boolean(default=False)


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
