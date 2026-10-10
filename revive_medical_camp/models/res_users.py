from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    camp_pmdc_number = fields.Char(
        string='PMDC number',
        help='Medical council registration. Required before this user can save a '
             'diagnosis or prescription in a medical camp.')
