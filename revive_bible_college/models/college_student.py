from odoo import api, fields, models

from .college_app_api import college_app_staff, public_student
from .college_enrollment import GRADE_POINTS


class CollegeStudent(models.Model):
    _name = 'college.student'
    _description = 'Bible College Student'
    _inherit = ['mail.thread']
    _order = 'name'

    student_code = fields.Char(readonly=True, copy=False,
                                default=lambda self: self.env['ir.sequence'].next_by_code('college.student'))
    name = fields.Char(required=True, tracking=True)
    email = fields.Char()
    phone = fields.Char()
    program_id = fields.Many2one('college.program', required=True, tracking=True)
    enrolled_term_id = fields.Many2one('college.term', string='Starting Term')
    applicant_id = fields.Many2one('college.applicant', readonly=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('graduated', 'Graduated'),
        ('withdrawn', 'Withdrawn'),
    ], default='active', required=True, tracking=True)
    enrollment_ids = fields.One2many('college.enrollment', 'student_id', string='Course Enrollments')
    enrollment_count = fields.Integer(compute='_compute_enrollment_count')
    completed_credits = fields.Float(compute='_compute_transcript')
    gpa = fields.Float(compute='_compute_transcript', string='GPA', digits=(3, 2))
    bible_knowledge_ids = fields.One2many('college.bible.knowledge', 'student_id', string='Bible Knowledge Records')
    competency_assessment_ids = fields.One2many(
        'college.competency.assessment', 'student_id', string='Competency Assessments')
    sermon_ids = fields.One2many('college.sermon', 'student_id', string='Sermons')
    formation_ids = fields.One2many('college.formation', 'student_id', string='Spiritual Formation Records')
    placement_ids = fields.One2many('college.placement', 'student_id', string='Fieldwork Placements')
    fee_ids = fields.One2many('college.fee', 'student_id', string='Fees')
    clearance_ids = fields.One2many('college.graduation.clearance', 'student_id', string='Graduation Clearances')

    def _compute_enrollment_count(self):
        for student in self:
            student.enrollment_count = len(student.enrollment_ids)

    @api.depends('enrollment_ids.grade_state', 'enrollment_ids.letter_grade', 'enrollment_ids.credits_earned')
    def _compute_transcript(self):
        for student in self:
            published = student.enrollment_ids.filtered(lambda e: e.grade_state == 'published')
            student.completed_credits = sum(published.mapped('credits_earned'))
            points = sum(GRADE_POINTS.get(e.letter_grade, 0.0) * e.credits_earned for e in published)
            credits = sum(published.mapped('credits_earned'))
            student.gpa = points / credits if credits else 0.0

    # ── App API (Phase 8: staff side) ────────────────────────────

    def _app_summary(self):
        return {
            'id': self.id, 'code': self.student_code or '', 'name': self.name,
            'email': self.email or '', 'phone': self.phone or '',
            'program_id': self.program_id.id, 'program_name': self.program_id.name,
            'state': self.state, 'gpa': self.gpa, 'completed_credits': self.completed_credits,
        }

    def _app_detail(self, viewer_is_admin=False):
        data = self._app_summary()
        data['has_password'] = self.has_password
        data['viewer_is_admin'] = viewer_is_admin
        data['enrollments'] = [{
            'id': e.id, 'course_id': e.course_id.id, 'course_name': e.course_id.name,
            'term_id': e.term_id.id, 'term_name': e.term_id.name,
            'state': e.state, 'grade_state': e.grade_state,
            'numeric_grade': e.numeric_grade, 'letter_grade': e.letter_grade or '',
        } for e in self.enrollment_ids]
        return data

    @api.model
    def app_college_get_students(self, query=''):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        domain = [('name', 'ilike', query)] if query else []
        students = self.sudo().search(domain, order='name', limit=200)
        return {'success': True, 'students': [s._app_summary() for s in students]}

    @api.model
    def app_college_get_student(self, student_id):
        staff, is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        student = self.sudo().browse(student_id)
        if not student.exists():
            return {'success': False, 'error': 'Student not found'}
        return {'success': True, 'student': student._app_detail(is_admin)}

    @api.model
    def app_college_enroll_student(self, student_id, course_id, term_id):
        staff, is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        student = self.sudo().browse(student_id)
        if not student.exists():
            return {'success': False, 'error': 'Student not found'}
        existing = self.env['college.enrollment'].sudo().search([
            ('student_id', '=', student_id), ('course_id', '=', course_id), ('term_id', '=', term_id),
        ], limit=1)
        if existing:
            return {'success': False, 'error': 'Already enrolled in this course for this term'}
        self.env['college.enrollment'].sudo().create({
            'student_id': student_id, 'course_id': course_id, 'term_id': term_id,
        })
        return {'success': True, 'student': student._app_detail(is_admin)}

    @api.model
    def app_college_get_student_progress(self, student_id):
        """Staff/admin view of one student's LMS journey -- the exact same
        per-course lesson/quiz/flashcard/certificate detail a student sees
        about themselves (see _app_self_detail below), plus their earned
        badges. Reuses that computation rather than deriving it twice."""
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        student = self.sudo().browse(student_id)
        if not student.exists():
            return {'success': False, 'error': 'Student not found'}
        detail = student._app_self_detail()
        return {'success': True, 'enrollments': detail['enrollments'], 'badges': detail['badges']}

    # ── App API (student's own view) ─────────────────────────────
    # Grades only show once published: a student must never see a grade
    # before staff releases it. See college_student_auth.py for sign-in.

    def _app_self_detail(self):
        data = self._app_summary()
        data['enrollments'] = [self._app_self_enrollment(e) for e in self.enrollment_ids]
        badges = self.env['college.badge.award'].sudo().search([('student_id', '=', self.id)], order='awarded_date desc')
        data['badges'] = [b._app_payload() for b in badges]
        return data

    def _app_self_enrollment(self, enrollment):
        """One enrollment's modules, lessons and this student's progress on
        each — the student's own course_id.content_ids rows that have no
        module yet (shouldn't happen after the 19.0.1.12.0 migration, but
        kept as a safety net) are listed under a final "More" module so
        nothing a teacher posted is ever silently hidden."""
        self.ensure_one()
        progress_by_content = {
            p.content_id.id: p
            for p in self.env['college.lesson.progress'].sudo().search([
                ('student_id', '=', self.id), ('content_id.course_id', '=', enrollment.course_id.id),
            ])
        }
        total_lessons = 0
        done_lessons = 0
        best_by_quiz = {}
        attempts_by_quiz = {}
        for attempt in self.env['college.quiz.attempt'].sudo().search([('student_id', '=', self.id)]):
            best_by_quiz[attempt.quiz_id.id] = max(best_by_quiz.get(attempt.quiz_id.id, 0.0), attempt.score)
            attempts_by_quiz[attempt.quiz_id.id] = attempts_by_quiz.get(attempt.quiz_id.id, 0) + 1
        known_by_deck = {}
        for progress in self.env['college.flashcard.progress'].sudo().search([('student_id', '=', self.id), ('known', '=', True)]):
            deck_id = progress.card_id.deck_id.id
            known_by_deck[deck_id] = known_by_deck.get(deck_id, 0) + 1

        def lesson_data(content):
            nonlocal total_lessons, done_lessons
            progress = progress_by_content.get(content.id)
            completed = bool(progress and progress.completed)
            total_lessons += 1
            if completed:
                done_lessons += 1
            return {
                'id': content.id, 'name': content.name, 'content_type': content.content_type,
                'url': content.url or '', 'body': content.body or '', 'has_attachment': bool(content.attachment),
                'completed': completed,
                'video_position': progress.video_position if progress else 0.0,
                'last_accessed': progress.write_date.isoformat() if progress and progress.write_date else '',
                'quiz_best_score': best_by_quiz.get(content.quiz_id.id),
                'quiz_attempt_count': attempts_by_quiz.get(content.quiz_id.id, 0),
                'flashcards_known': known_by_deck.get(content.deck_id.id, 0),
                'flashcards_total': len(content.deck_id.card_ids),
            }

        modules = [{
            'id': module.id, 'name': module.name,
            'lessons': [lesson_data(c) for c in module.lesson_ids.sorted('sequence')],
        } for module in enrollment.course_id.module_ids.sorted('sequence')]
        unfiled = enrollment.course_id.content_ids.filtered(lambda c: not c.module_id).sorted('sequence')
        if unfiled:
            modules.append({'id': 0, 'name': 'More', 'lessons': [lesson_data(c) for c in unfiled]})
        certificate = self.env['college.certificate'].sudo().search([
            ('student_id', '=', self.id), ('enrollment_id', '=', enrollment.id),
        ], limit=1)
        return {
            'id': enrollment.id, 'course_id': enrollment.course_id.id, 'course_name': enrollment.course_id.name,
            'term_id': enrollment.term_id.id, 'term_name': enrollment.term_id.name,
            'state': enrollment.state,
            'letter_grade': enrollment.letter_grade if enrollment.grade_state == 'published' else '',
            'grade_pending': enrollment.grade_state != 'published',
            'modules': modules,
            'percent_complete': round(done_lessons / total_lessons * 100) if total_lessons else 0,
            'lesson_count': total_lessons,
            'lessons_done': done_lessons,
            'certificate_eligible': total_lessons > 0 and done_lessons == total_lessons,
            'certificate_issued': bool(certificate),
        }

    @api.model
    def app_college_student_lookup(self, code, email):
        student = public_student(self.env, code, email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        return {'success': True, 'student': student._app_self_detail()}
