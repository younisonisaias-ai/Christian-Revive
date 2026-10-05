# -*- coding: utf-8 -*-
import secrets

from odoo import models, fields, api


class LifestyleVendorSession(models.Model):
    """A token issued to a carpenter/vendor after a successful App Login
    Email + App PIN check, used instead of a real Odoo user session so
    vendor staff don't need a full Odoo account just to send photos."""
    _name = 'lifestyle.vendor.session'
    _description = 'Vendor App PIN Login Session'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    token = fields.Char(string='Token', required=True, index=True, default=lambda self: secrets.token_urlsafe(32))

    _token_unique = models.Constraint(
        'unique(token)',
        'Token must be unique.',
    )

    @api.model
    def issue_for(self, employee):
        return self.create({'employee_id': employee.id})
