"""Referral to a partner hospital, tracked until the patient attends."""
from odoo import api, fields, models


class CampReferral(models.Model):
    _name = 'camp.referral'
    _description = 'Camp Referral'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    consultation_id = fields.Many2one('camp.consultation', ondelete='set null', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True, index=True)
    patient_phone = fields.Char(related='patient_id.phone')
    hospital_id = fields.Many2one('res.partner', string='Hospital', required=True,
                                  help='Partner hospital or clinic the patient is sent to.')
    department = fields.Char(help='e.g. Eye OPD, Gynae, Cardiology')
    reason = fields.Text(required=True, tracking=True)
    urgency = fields.Selection([
        ('routine', 'Routine'), ('soon', 'Within a week'), ('urgent', 'Urgent (today)'),
    ], default='routine', required=True, tracking=True)
    referred_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    status = fields.Selection([
        ('issued', 'Letter issued'), ('attended', 'Attended'), ('closed', 'Closed'),
    ], default='issued', required=True, tracking=True)
    outcome = fields.Text(help='What happened at the hospital (filled in by follow-up).')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('consultation_id') and not vals.get('visit_id'):
                vals['visit_id'] = self.env['camp.consultation'].browse(vals['consultation_id']).visit_id.id
        return super().create(vals_list)

    def action_attended(self):
        self.write({'status': 'attended'})

    def action_close(self):
        self.write({'status': 'closed'})

    def action_print_letter(self):
        return self.env.ref('revive_medical_camp.action_report_referral_letter').report_action(self)
