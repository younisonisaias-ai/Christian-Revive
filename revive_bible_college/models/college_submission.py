from odoo import api, fields, models


class CollegeSubmission(models.Model):
    _name = 'college.submission'
    _description = 'Bible College Assignment Submission'
    _order = 'id desc'

    assignment_id = fields.Many2one('college.assignment', required=True, ondelete='cascade')
    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('graded', 'Graded'),
    ], default='draft', required=True)
    submitted_date = fields.Datetime(readonly=True, copy=False)
    attachment = fields.Binary(attachment=True)
    attachment_filename = fields.Char()
    text_answer = fields.Text()
    score = fields.Float()
    feedback = fields.Text()
    is_late = fields.Boolean(compute='_compute_is_late')

    _assignment_student_uniq = models.Constraint(
        'unique(assignment_id, student_id)',
        'This student already has a submission for this assignment.',
    )

    @api.depends('submitted_date', 'assignment_id.due_date')
    def _compute_is_late(self):
        for submission in self:
            due = submission.assignment_id.due_date
            submission.is_late = bool(
                submission.submitted_date and due
                and submission.submitted_date.date() > due
            )

    def action_submit(self):
        for submission in self:
            if submission.state != 'draft':
                continue
            submission.write({'state': 'submitted', 'submitted_date': fields.Datetime.now()})

    def action_mark_graded(self):
        for submission in self:
            if submission.state != 'submitted':
                continue
            submission.state = 'graded'

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'submitted_date': False})
