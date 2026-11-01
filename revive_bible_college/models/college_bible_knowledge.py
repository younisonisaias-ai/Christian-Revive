from odoo import fields, models


class CollegeBibleKnowledge(models.Model):
    _name = 'college.bible.knowledge'
    _description = 'Bible Knowledge / Scripture Memory Record'
    _order = 'date desc, id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    course_id = fields.Many2one('college.course')
    category = fields.Selection([
        ('memory', 'Scripture Memory'),
        ('quiz', 'Bible Knowledge Quiz'),
        ('reading', 'Reading Check'),
    ], default='memory', required=True)
    passage = fields.Char(string='Passage / Topic', help='e.g. "John 3:16-21"')
    score = fields.Float(help='Quiz or reading check score, 0-100. Leave blank for scripture memory.')
    verified = fields.Boolean(string='Verified by Staff')
    verified_by = fields.Many2one('res.users', readonly=True, copy=False)
    date = fields.Date(default=fields.Date.context_today, required=True)
    notes = fields.Text()

    def action_verify(self):
        self.write({'verified': True, 'verified_by': self.env.user.id})
