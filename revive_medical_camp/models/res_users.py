from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    camp_is_hospital = fields.Boolean(
        string='Medical camp referral hospital',
        help='Offered to camp doctors when they refer a patient.')


class ResUsers(models.Model):
    _inherit = 'res.users'

    camp_pmdc_number = fields.Char(
        string='PMDC number',
        help='Medical council registration. Required before this user can save a '
             'diagnosis or prescription in a medical camp.')
    camp_pmdc_expiry = fields.Date(
        string='PMDC valid until',
        help='The camp warns the coordinator and the doctor when it has expired or expires soon.')
