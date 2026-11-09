from odoo import api, fields, models

from .college_app_api import token_student


class CollegeFlashcardDeck(models.Model):
    """A reusable set of study cards. Attach one to a lesson by setting
    that lesson's content_type to 'flashcards' and deck_id to this record
    (see college_course_content.py), the same way a quiz attaches."""
    _name = 'college.flashcard.deck'
    _description = 'Bible College Flashcard Deck'
    _order = 'name'

    name = fields.Char(translate=True, required=True)
    description = fields.Text(translate=True)
    card_ids = fields.One2many('college.flashcard', 'deck_id', string='Cards')
    card_count = fields.Integer(compute='_compute_card_count')

    def _compute_card_count(self):
        for deck in self:
            deck.card_count = len(deck.card_ids)

    def action_view_cards(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cards',
            'res_model': 'college.flashcard',
            'view_mode': 'list,form',
            'domain': [('deck_id', '=', self.id)],
            'context': {'default_deck_id': self.id},
        }

    # ── App API (student's own view, token-only) ──────────────────
    # Flashcards are self-study — unlike a quiz, there is no answer to
    # hide, so both sides of every card go to the app up front.

    def _enrolled_deck_content(self, student, content_id):
        """The college.course.content row for this deck, if the student is
        enrolled in its course, else an empty recordset."""
        content = self.env['college.course.content'].sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.content_type != 'flashcards' or not content.deck_id:
            return self.env['college.course.content']
        if content.course_id.id not in enrolled_course_ids:
            return self.env['college.course.content']
        return content

    @api.model
    def app_college_my_flashcards(self, token, content_id):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self._enrolled_deck_content(student, content_id)
        if not content:
            return {'success': False, 'error': 'Not found'}
        deck = content.deck_id.sudo()
        known_ids = set(self.env['college.flashcard.progress'].sudo().search([
            ('student_id', '=', student.id), ('card_id.deck_id', '=', deck.id), ('known', '=', True),
        ]).card_id.ids)
        return {
            'success': True,
            'deck': {
                'id': deck.id, 'name': deck.name, 'description': deck.description or '',
                'cards': [{
                    'id': c.id, 'front': c.front, 'back': c.back, 'known': c.id in known_ids,
                } for c in deck.card_ids.sorted('sequence')],
            },
        }

    @api.model
    def app_college_my_flashcard_mark(self, token, content_id, card_id, known):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self._enrolled_deck_content(student, content_id)
        if not content:
            return {'success': False, 'error': 'Not found'}
        card = self.env['college.flashcard'].sudo().browse(card_id)
        if not card.exists() or card.deck_id.id != content.deck_id.id:
            return {'success': False, 'error': 'Not found'}
        Progress = self.env['college.flashcard.progress'].sudo()
        progress = Progress.search([('student_id', '=', student.id), ('card_id', '=', card_id)], limit=1)
        vals = {'known': bool(known), 'last_studied': fields.Datetime.now()}
        if progress:
            progress.write(vals)
        else:
            Progress.create({**vals, 'student_id': student.id, 'card_id': card_id})

        deck = content.deck_id
        known_count = Progress.search_count([
            ('student_id', '=', student.id), ('card_id.deck_id', '=', deck.id), ('known', '=', True),
        ])
        deck_complete = known_count >= len(deck.card_ids)
        if deck_complete:
            LessonProgress = self.env['college.lesson.progress'].sudo()
            lesson_progress = LessonProgress.search([('student_id', '=', student.id), ('content_id', '=', content.id)], limit=1)
            if lesson_progress:
                lesson_progress.write({'completed': True, 'completed_date': fields.Datetime.now()})
            else:
                LessonProgress.create({'student_id': student.id, 'content_id': content.id, 'completed': True,
                                       'completed_date': fields.Datetime.now()})
            Badge = self.env['college.badge.award'].sudo()
            Badge._award(student, 'first_deck_mastered')
            Badge._check_lesson_complete(student, content)
        return {'success': True, 'deck_complete': deck_complete}


class CollegeFlashcard(models.Model):
    _name = 'college.flashcard'
    _description = 'Bible College Flashcard'
    _order = 'deck_id, sequence, id'
    _rec_name = 'front'

    deck_id = fields.Many2one('college.flashcard.deck', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    front = fields.Text(translate=True, required=True, help='What the student sees first — a verse reference, a term, a question.')
    back = fields.Text(translate=True, required=True, help='What the student sees after turning the card over.')


class CollegeFlashcardProgress(models.Model):
    """One student's standing on one card: whether they currently know it.
    Re-studying a card just overwrites this — there is no history kept,
    unlike a quiz attempt, since there is nothing here to grade."""
    _name = 'college.flashcard.progress'
    _description = "A student's flashcard progress"
    _order = 'id desc'
    _rec_name = 'card_id'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    card_id = fields.Many2one('college.flashcard', required=True, ondelete='cascade', index=True)
    known = fields.Boolean(default=False)
    last_studied = fields.Datetime()

    _student_card_uniq = models.Constraint('unique(student_id, card_id)', 'Already have progress for this card.')
