from odoo import api, fields, models

# A small, fixed set of quiet, personal milestones — no points, no
# leaderboard, no comparison between students (the user's explicit choice
# for this module's gamification). Staff never hand these out; the server
# awards one automatically, once, the first time a student reaches it.
BADGE_CATALOG = {
    'first_lesson': {'name': 'First Steps', 'description': 'Complete your first lesson.'},
    'first_quiz_passed': {'name': 'Quiz Whiz', 'description': 'Pass your first quiz.'},
    'perfect_quiz_score': {'name': 'Perfect Score', 'description': 'Score 100% on a quiz.'},
    'first_deck_mastered': {'name': 'Card Master', 'description': 'Know every card in a flashcard deck.'},
    'first_course_complete': {'name': 'Course Complete', 'description': 'Finish every lesson in a course.'},
}


class CollegeBadgeAward(models.Model):
    """One student earning one badge, once. Permanent once awarded — a
    lesson being un-marked afterward does not take a badge back, the same
    'once complete, stays complete' rule used for lesson/quiz/flashcard
    progress and certificates."""
    _name = 'college.badge.award'
    _description = 'Bible College Badge Award'
    _order = 'awarded_date desc'
    _rec_name = 'kind'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([(k, v['name']) for k, v in BADGE_CATALOG.items()], required=True)
    awarded_date = fields.Datetime(required=True, default=fields.Datetime.now)

    _student_kind_uniq = models.Constraint('unique(student_id, kind)', 'This badge was already awarded.')

    def _app_payload(self):
        self.ensure_one()
        info = BADGE_CATALOG.get(self.kind, {})
        return {
            'kind': self.kind, 'name': info.get('name', self.kind), 'description': info.get('description', ''),
            'awarded_date': self.awarded_date.isoformat() if self.awarded_date else '',
        }

    @api.model
    def _award(self, student, kind):
        """A no-op if the student already has this badge."""
        if kind not in BADGE_CATALOG:
            return
        if self.sudo().search_count([('student_id', '=', student.id), ('kind', '=', kind)]):
            return
        self.sudo().create({'student_id': student.id, 'kind': kind})

    @api.model
    def _check_lesson_complete(self, student, content):
        """Call right after any lesson is marked complete (a plain
        material, or a quiz/flashcard lesson completing itself): the
        first-ever-lesson badge, and whether that lesson's course just
        became fully complete for the first time anywhere."""
        self._award(student, 'first_lesson')
        course = content.course_id
        if not course:
            return
        total = len(course.content_ids)
        if not total:
            return
        done = self.env['college.lesson.progress'].sudo().search_count([
            ('student_id', '=', student.id), ('content_id.course_id', '=', course.id), ('completed', '=', True),
        ])
        if done >= total:
            self._award(student, 'first_course_complete')
