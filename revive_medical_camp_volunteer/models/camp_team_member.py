from odoo import api, fields, models


class CampTeamMember(models.Model):
    _inherit = 'camp.team.member'

    volunteer_id = fields.Many2one('res.partner', string='Volunteer', domain=[('is_volunteer', '=', True)],
                                   help='Pick from the volunteer list; name and phone are filled in.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('volunteer_id'):
                volunteer = self.env['res.partner'].browse(vals['volunteer_id'])
                vals.setdefault('name', volunteer.name)
                vals.setdefault('phone', volunteer.phone)
        return super().create(vals_list)

    @api.onchange('volunteer_id')
    def _onchange_volunteer_id(self):
        if self.volunteer_id:
            self.name = self.volunteer_id.name
            self.phone = self.phone or self.volunteer_id.phone
