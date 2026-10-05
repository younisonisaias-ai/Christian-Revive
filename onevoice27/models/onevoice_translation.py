# -*- coding: utf-8 -*-
from odoo import models, fields, api


class OnevoiceTranslation(models.Model):
    _name        = 'onevoice.translation'
    _description = 'Urdu Translation Override'
    _order       = 'source_text'

    source_text     = fields.Char(string='English Text',       required=True)
    translated_text = fields.Char(string='Urdu Translation',   required=True)
    notes           = fields.Char(string='Notes (optional)',   help='Admin reference — e.g. "used in Gospel quiz Q3"')
    is_active       = fields.Boolean(string='Active', default=True)

    _source_text_uniq = models.Constraint(
        'unique(source_text)',
        'An override for this English text already exists.',
    )

    @api.model
    def app_get_translations(self):
        """Return all active overrides as a flat {english: urdu} dict for the Flutter app."""
        records = self.sudo().search([('is_active', '=', True)])
        return {r.source_text: r.translated_text for r in records}
