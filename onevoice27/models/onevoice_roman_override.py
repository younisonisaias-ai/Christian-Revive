# -*- coding: utf-8 -*-
from odoo import models, fields, api


class OnevoiceRomanOverride(models.Model):
    _name        = 'onevoice.roman.override'
    _description = 'Roman Word Override (shown in Urdu mode)'
    _order       = 'source_text'

    source_text = fields.Char(string='Urdu Word / Phrase',  required=True,
                               help='The Urdu word or phrase to replace (e.g. ایمانوایل)')
    roman_text  = fields.Char(string='Roman Replacement',   required=True,
                               help='The Roman/Latin text to show instead (e.g. Immanuel)')
    notes       = fields.Char(string='Notes (optional)',    help='Admin reference — e.g. "chapter 1 proper noun"')
    is_active   = fields.Boolean(string='Active', default=True)

    _source_text_uniq = models.Constraint(
        'unique(source_text)',
        'An override for this word already exists.',
    )

    @api.model
    def app_get_roman_translations(self):
        """Return all active overrides as {urdu_word: roman_text} dict for the Flutter app.
        Applied in Urdu mode — specific Urdu words display as Roman/Latin text."""
        records = self.sudo().search([('is_active', '=', True)])
        return {r.source_text: r.roman_text for r in records}
