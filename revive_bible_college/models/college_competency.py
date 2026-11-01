from odoo import fields, models


class CollegeCompetency(models.Model):
    _name = 'college.competency'
    _description = 'Ministry Competency'
    _order = 'name'

    name = fields.Char(required=True, help='e.g. "Preaching", "Pastoral Care", "Biblical Exegesis"')
    description = fields.Text()
    active = fields.Boolean(default=True)


class CollegeCompetencyAssessment(models.Model):
    _name = 'college.competency.assessment'
    _description = 'Ministry Competency Assessment'
    _order = 'date desc, id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    competency_id = fields.Many2one('college.competency', required=True)
    course_id = fields.Many2one('college.course')
    term_id = fields.Many2one('college.term')
    level = fields.Selection([
        ('novice', 'Novice'),
        ('developing', 'Developing'),
        ('proficient', 'Proficient'),
        ('advanced', 'Advanced'),
    ], default='novice', required=True)
    assessed_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    notes = fields.Text()
