from odoo import fields, models


class CollegeFormation(models.Model):
    _name = 'college.formation'
    _description = 'Spiritual Formation Record'
    _order = 'date desc, id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    activity_type = fields.Selection([
        ('devotional', 'Personal Devotional'),
        ('mentoring', 'Mentoring Session'),
        ('retreat', 'Retreat / Chapel'),
        ('service', 'Community Service'),
        ('other', 'Other'),
    ], default='devotional', required=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    description = fields.Text()
    hours = fields.Float()
    mentor_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    verified = fields.Boolean()
