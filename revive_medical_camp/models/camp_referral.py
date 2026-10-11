"""Referral to a partner hospital, tracked until the patient attends."""
import secrets

from odoo import _, api, fields, models


def _new_code():
    return secrets.token_urlsafe(24)


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
    # The QR code on the letter opens a page where the hospital confirms arrival.
    confirm_code = fields.Char(copy=False, readonly=True, index=True, default=lambda self: _new_code())
    confirm_url = fields.Char(string='Hospital confirmation link', compute='_compute_confirm_url')
    attended_at = fields.Datetime(string='Arrived at hospital', readonly=True)
    received_by = fields.Char(string='Confirmed by (hospital)', readonly=True)

    def _compute_confirm_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        for r in self:
            r.confirm_url = f'{base}/camp/referral/{r.confirm_code}' if r.confirm_code else False

    def _confirm_arrival(self, received_by=''):
        """The hospital scanned the letter: no follow-up call or reminder needed."""
        self.sudo().write({'status': 'attended', 'attended_at': fields.Datetime.now(),
                           'received_by': received_by or False})
        self.env['camp.followup'].sudo().search(
            [('referral_id', 'in', self.ids), ('state', 'in', ('to_call', 'no_answer'))]
        ).write({'state': 'closed', 'outcome': _('The hospital confirmed the patient arrived.')})
        self.env['camp.reminder'].sudo().search(
            [('referral_id', 'in', self.ids), ('state', '=', 'to_send')]).write({'state': 'skipped'})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('consultation_id') and not vals.get('visit_id'):
                vals['visit_id'] = self.env['camp.consultation'].browse(vals['consultation_id']).visit_id.id
        referrals = super().create(vals_list)
        for r in referrals:
            self.env['camp.followup']._ensure(
                r.visit_id, 'referral', _('Check the patient went to %s', r.hospital_id.name),
                referral=r, days=1 if r.urgency == 'urgent' else 3)
        return referrals

    def action_attended(self):
        self.write({'status': 'attended', 'attended_at': fields.Datetime.now()})

    def action_close(self):
        self.write({'status': 'closed'})

    def action_print_letter(self):
        return self.env.ref('revive_medical_camp.action_report_referral_letter').report_action(self)
