# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StudyBook(models.Model):
    _name        = 'onevoice.study.book'
    _description = 'Study Book'
    _order       = 'sequence, name'

    name         = fields.Char(string='Book Name', required=True)
    book_code    = fields.Char(string='Book Code', required=True,
                               help='Unique slug used by the Flutter app, e.g. desire_of_ages')
    sequence     = fields.Integer(string='Sequence', default=10)
    is_published   = fields.Boolean(string='Published', default=True)
    available_from = fields.Datetime(
        string='Available From',
        help='Leave empty to make available immediately. Set a future date/time to lock this entire book until then.')
    chapter_ids  = fields.One2many('onevoice.doa.chapter', 'book_id', string='Chapters')
    mcq_ids      = fields.One2many('onevoice.study.mcq', 'book_id', string='MCQs')

    _book_code_uniq = models.Constraint(
        'unique(book_code)',
        'A book with this code already exists.',
    )

    @api.model
    def app_get_books(self):
        """Return list of published books for the Flutter app."""
        books = self.sudo().search([('is_published', '=', True)], order='sequence, name')
        return [{
            'book_code':      b.book_code,
            'name':           b.name,
            'available_from': (b.available_from.strftime('%Y-%m-%dT%H:%M:%SZ')
                               if b.available_from else False),
        } for b in books]

    @api.model
    def app_get_chapter_list(self, book_code):
        """Return chapter numbers and titles (no body text) for a book."""
        chapters = self.env['onevoice.doa.chapter'].sudo().search([
            ('book_id.book_code', '=', book_code),
            ('is_published', '=', True),
        ], order='chapter_number')
        return [{
            'chapter_number': c.chapter_number,
            'title_en':       c.title_en or '',
            'title_ur':       c.title_ur or '',
            'available_from': (c.available_from.strftime('%Y-%m-%dT%H:%M:%SZ')
                               if c.available_from else False),
            'mcq_count':      len(c.mcq_ids.filtered(lambda x: x.is_published)),
        } for c in chapters]

    @api.model
    def app_get_chapter(self, book_code, chapter_number):
        """Return full chapter content for the Flutter app."""
        chapter = self.env['onevoice.doa.chapter'].sudo().search([
            ('book_id.book_code', '=', book_code),
            ('chapter_number', '=', chapter_number),
            ('is_published', '=', True),
        ], limit=1)
        if not chapter:
            return False
        correct_map = {'a': 0, 'b': 1, 'c': 2, 'd': 3}
        mcqs = []
        for m in chapter.mcq_ids.filtered(lambda x: x.is_published).sorted('sequence'):
            opts_en = [o for o in [m.option_a_en, m.option_b_en, m.option_c_en, m.option_d_en] if o]
            opts_ur = [o for o in [m.option_a_ur, m.option_b_ur, m.option_c_ur, m.option_d_ur] if o]
            mcqs.append({
                'question_en':    m.question_en or '',
                'question_ur':    m.question_ur or '',
                'options_en':     opts_en,
                'options_ur':     opts_ur,
                'correct_index':  correct_map.get(m.correct_option, 0),
                'explanation_en': m.explanation_en or '',
                'explanation_ur': m.explanation_ur or '',
                'show_on_wrong':  m.show_on_wrong,
                'show_on_correct': m.show_on_correct,
            })
        return {
            'chapter_number': chapter.chapter_number,
            'title_en':       chapter.title_en or '',
            'text_en':        chapter.text_en  or '',
            'title_ur':       chapter.title_ur or '',
            'text_ur':        chapter.text_ur  or '',
            'available_from': (chapter.available_from.strftime('%Y-%m-%dT%H:%M:%SZ')
                               if chapter.available_from else False),
            'mcqs':           mcqs,
        }

    @api.model
    def app_get_published_numbers(self, book_code):
        """Return sorted list of published chapter numbers for a given book."""
        chapters = self.env['onevoice.doa.chapter'].sudo().search([
            ('book_id.book_code', '=', book_code),
            ('is_published', '=', True),
        ])
        return sorted(c.chapter_number for c in chapters)
