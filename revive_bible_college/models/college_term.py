from odoo import fields, models


class CollegeTerm(models.Model):
    _name = 'college.term'
    _description = 'Bible College Academic Term'
    _order = 'start_date desc'

    name = fields.Char(translate=True, required=True, help='e.g. "Fall 2026"')
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], default='draft', required=True)

    def action_activate(self):
        self.write({'state': 'active'})

    def action_close(self):
        self.write({'state': 'closed'})
