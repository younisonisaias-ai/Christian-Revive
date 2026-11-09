import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .college_app_api import token_student

_CLOCK_RE = re.compile(r'^\s*(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)\s*$')


def parse_clock(text):
    """Seconds from "4:30" or "1:02:30", or None if it isn't a time."""
    match = _CLOCK_RE.match(text or '')
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    if hours and int(minutes) > 59:
        return None
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


class CollegeVideoQuestion(models.Model):
    """A question that pauses a video lesson at a set moment. Practice only:
    answers never affect a grade or quiz score; they are kept so staff can
    later see which questions students find hard."""
    _name = 'college.video.question'
    _description = 'Bible College In-Video Question'
    _order = 'content_id, pause_seconds, sequence, id'
    _rec_name = 'text'

    content_id = fields.Many2one('college.course.content', string='Lesson', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    pause_time = fields.Char(string='Pause at', required=True, help='When the video pauses, e.g. 4:30 or 1:02:30.')
    pause_seconds = fields.Integer(compute='_compute_pause_seconds', store=True)
    text = fields.Text(string='Question', required=True)
    option_ids = fields.One2many('college.video.question.option', 'question_id', string='Answers', copy=True)
    explanation = fields.Text(help='Shown after the student answers, right or wrong.')
    has_correct_option = fields.Boolean(compute='_compute_has_correct_option',
                                        help='A question with no correct answer marked can never be answered right.')
    answer_count = fields.Integer(compute='_compute_answer_stats')
    correct_percent = fields.Float(compute='_compute_answer_stats', string='Answered right (%)')

    @api.depends('pause_time')
    def _compute_pause_seconds(self):
        for question in self:
            question.pause_seconds = parse_clock(question.pause_time) or 0

    @api.constrains('pause_time')
    def _check_pause_time(self):
        for question in self:
            if parse_clock(question.pause_time) is None:
                raise ValidationError(_('"%s" is not a time. Write it like 4:30 or 1:02:30.') % (question.pause_time or ''))

    @api.depends('option_ids.is_correct')
    def _compute_has_correct_option(self):
        for question in self:
            question.has_correct_option = any(question.option_ids.mapped('is_correct'))

    def _compute_answer_stats(self):
        groups = self.env['college.video.question.answer'].sudo()._read_group(
            [('question_id', 'in', self.ids)], ['question_id', 'is_correct'], ['__count'])
        stats = {}
        for question, is_correct, count in groups:
            total, right = stats.get(question.id, (0, 0))
            stats[question.id] = (total + count, right + (count if is_correct else 0))
        for question in self:
            total, right = stats.get(question.id, (0, 0))
            question.answer_count = total
            question.correct_percent = 100.0 * right / total if total else 0.0

    def _app_payload(self, answered_ids):
        """For the app: never says which answer is correct."""
        return [{
            'id': q.id, 'seconds': q.pause_seconds, 'text': q.text,
            'options': [{'id': o.id, 'text': o.text} for o in q.option_ids],
            'answered': q.id in answered_ids,
        } for q in self if q.option_ids]

    @api.model
    def app_college_my_video_answer(self, token, question_id, option_id):
        """Checks one answer on the server and keeps it (latest answer wins)."""
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        question = self.sudo().browse(int(question_id))
        if not question.exists() or question.content_id.course_id.id not in set(student.enrollment_ids.course_id.ids):
            return {'success': False, 'error': 'Not found'}
        option = question.option_ids.filtered(lambda o: o.id == int(option_id))
        if not option:
            return {'success': False, 'error': 'Not found'}
        Answer = self.env['college.video.question.answer'].sudo()
        vals = {'option_id': option.id, 'is_correct': option.is_correct, 'answered_date': fields.Datetime.now()}
        answer = Answer.search([('student_id', '=', student.id), ('question_id', '=', question.id)], limit=1)
        if answer:
            answer.write(vals)
        else:
            Answer.create({**vals, 'student_id': student.id, 'question_id': question.id})
        correct = question.option_ids.filtered('is_correct')[:1]
        return {
            'success': True, 'is_correct': option.is_correct,
            'correct_option_id': correct.id or False, 'explanation': question.explanation or '',
        }


class CollegeVideoQuestionOption(models.Model):
    _name = 'college.video.question.option'
    _description = 'Bible College In-Video Question Answer'
    _order = 'question_id, sequence, id'
    _rec_name = 'text'

    question_id = fields.Many2one('college.video.question', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    text = fields.Char(string='Answer', required=True)
    is_correct = fields.Boolean(string='Correct')


class CollegeVideoQuestionAnswer(models.Model):
    """A student's answer to an in-video question."""
    _name = 'college.video.question.answer'
    _description = "A student's answer to an in-video question"
    _order = 'answered_date desc, id desc'
    _rec_name = 'question_id'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one('college.video.question', required=True, ondelete='cascade', index=True)
    option_id = fields.Many2one('college.video.question.option', ondelete='set null')
    is_correct = fields.Boolean()
    answered_date = fields.Datetime()

    _student_question_uniq = models.Constraint(
        'unique(student_id, question_id)', 'Already have an answer from this student for this question.')
