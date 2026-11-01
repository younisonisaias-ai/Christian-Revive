from odoo import api, fields, models


class CollegePlacement(models.Model):
    _name = 'college.placement'
    _description = 'Bible College Fieldwork / Ministry Placement'
    _order = 'start_date desc, id desc'
    _rec_name = 'site_name'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    term_id = fields.Many2one('college.term')
    site_name = fields.Char(required=True, help='e.g. "Grace Community Church"')
    site_address = fields.Char()
    supervisor_name = fields.Char(help='The field supervisor at the placement site (not a system user).')
    supervisor_contact = fields.Char(string='Supervisor Phone / Email')
    start_date = fields.Date()
    end_date = fields.Date()
    hours_required = fields.Float()
    hours_completed = fields.Float(compute='_compute_hours_completed', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('verified', 'Verified'),
    ], default='draft', required=True)
    verified_by = fields.Many2one('res.users', readonly=True, copy=False)
    verified_date = fields.Date(readonly=True, copy=False)
    log_ids = fields.One2many('college.placement.log', 'placement_id', string='Hours Log')
    notes = fields.Text()

    @api.depends('log_ids.hours')
    def _compute_hours_completed(self):
        for placement in self:
            placement.hours_completed = sum(placement.log_ids.mapped('hours'))

    def action_activate(self):
        self.filtered(lambda p: p.state == 'draft').write({'state': 'active'})

    def action_complete(self):
        self.filtered(lambda p: p.state == 'active').write({'state': 'completed'})

    def action_verify(self):
        for placement in self.filtered(lambda p: p.state == 'completed'):
            placement.write({
                'state': 'verified',
                'verified_by': self.env.user.id,
                'verified_date': fields.Date.context_today(self),
            })

    def action_reset_to_draft(self):
        self.write({'state': 'draft', 'verified_by': False, 'verified_date': False})


class CollegePlacementLog(models.Model):
    _name = 'college.placement.log'
    _description = 'Bible College Placement Hours Log'
    _order = 'date desc, id desc'
    _rec_name = 'placement_id'

    placement_id = fields.Many2one('college.placement', required=True, ondelete='cascade')
    date = fields.Date(default=fields.Date.context_today, required=True)
    hours = fields.Float(required=True)
    activity = fields.Char()
    logged_by = fields.Many2one('res.users', default=lambda self: self.env.user)
