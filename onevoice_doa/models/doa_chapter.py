# -*- coding: utf-8 -*-
from odoo import models, fields, api


class DoaChapter(models.Model):
    _name        = 'onevoice.doa.chapter'
    _description = 'Study Book Chapter'
    _order       = 'chapter_number'

    book_id        = fields.Many2one('onevoice.study.book', string='Book',
                                     ondelete='cascade')
    chapter_number = fields.Integer(string='Chapter #', required=True)
    name           = fields.Char(string='Name', compute='_compute_name', store=True)
    title_en       = fields.Char(string='English Title')
    text_en        = fields.Text(string='English Text')
    title_ur       = fields.Char(string='Urdu Title')
    text_ur        = fields.Text(string='Urdu Text')
    is_published   = fields.Boolean(string='Published', default=True)
    available_from = fields.Datetime(
        string='Available From',
        help='Leave empty to make available immediately. Set a future date/time to lock this chapter until then.')
    mcq_ids        = fields.One2many('onevoice.study.mcq', 'chapter_id', string='MCQs')

    @api.depends('book_id.name', 'chapter_number')
    def _compute_name(self):
        for rec in self:
            book = rec.book_id.name or 'Chapter'
            rec.name = f'{book} – Ch {rec.chapter_number}'

    _chapter_book_number_uniq = models.Constraint(
        'unique(book_id, chapter_number)',
        'A chapter with this number already exists in this book.',
    )

    @api.model
    def app_get_chapter(self, chapter_number):
        """Backward-compat: fetch a DOA (desire_of_ages) chapter by number."""
        rec = self.sudo().search([
            ('book_id.book_code', '=', 'desire_of_ages'),
            ('chapter_number', '=', chapter_number),
            ('is_published',   '=', True),
        ], limit=1)
        if not rec:
            # Fallback for records not yet linked to a book
            rec = self.sudo().search([
                ('book_id', '=', False),
                ('chapter_number', '=', chapter_number),
                ('is_published',   '=', True),
            ], limit=1)
        if not rec:
            return False
        return {
            'chapter_number': rec.chapter_number,
            'title_en':       rec.title_en or '',
            'text_en':        rec.text_en  or '',
            'title_ur':       rec.title_ur or '',
            'text_ur':        rec.text_ur  or '',
        }

    @api.model
    def app_get_published_numbers(self):
        """Backward-compat: published chapter numbers for desire_of_ages."""
        recs = self.sudo().search([
            ('book_id.book_code', '=', 'desire_of_ages'),
            ('is_published', '=', True),
        ])
        if not recs:
            recs = self.sudo().search([
                ('book_id', '=', False),
                ('is_published', '=', True),
            ])
        return sorted(r.chapter_number for r in recs)
