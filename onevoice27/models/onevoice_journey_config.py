# -*- coding: utf-8 -*-
from odoo import models, fields, api


class OnevoiceJourneyConfig(models.Model):
    _name        = 'onevoice.journey.config'
    _description = 'Prayer Journey Configuration'
    _order       = 'sequence, journey_key'

    journey_key  = fields.Char(
        string='Journey Key', required=True,
        help='Identifier used by the app: 40_days or 365_days')
    name         = fields.Char(string='Journey Name', required=True)
    description  = fields.Text(string='Description')
    sequence     = fields.Integer(string='Sequence', default=10)
    available_from = fields.Date(
        string='Available From',
        help='Leave empty to lock the journey. Set a date to unlock it on that day.')
    is_active    = fields.Boolean(string='Active', default=True)

    _journey_key_uniq = models.Constraint(
        'unique(journey_key)',
        'A journey with this key already exists.',
    )

    @api.model
    def app_get_journey_configs(self):
        """Return journey configs for the Flutter app keyed by journey_key."""
        records = self.sudo().search([('is_active', '=', True)], order='sequence, journey_key')
        return {
            r.journey_key: {
                'name':           r.name,
                'description':    r.description or '',
                'available_from': r.available_from.isoformat() if r.available_from else False,
            }
            for r in records
        }
