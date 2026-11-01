from odoo import fields, models


class CollegeAssignment(models.Model):
    _name = 'college.assignment'
    _description = 'Bible College Assignment'
    _order = 'due_date, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True)
    term_id = fields.Many2one('college.term', required=True)
    description = fields.Text()
    due_date = fields.Date()
    max_score = fields.Float(default=100.0)
    active = fields.Boolean(default=True)
    submission_ids = fields.One2many('college.submission', 'assignment_id', string='Submissions')
    submission_count = fields.Integer(compute='_compute_submission_count')

    def _compute_submission_count(self):
        for assignment in self:
            assignment.submission_count = len(assignment.submission_ids)

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submissions',
            'res_model': 'college.submission',
            'view_mode': 'list,form',
            'domain': [('assignment_id', '=', self.id)],
            'context': {'default_assignment_id': self.id},
        }
