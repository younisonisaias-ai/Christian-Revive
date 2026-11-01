from odoo import api, fields, models

from .college_app_api import college_app_staff
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

    def _app_detail(self):
        data = self._app_summary()
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
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        student = self.sudo().browse(student_id)
        if not student.exists():
            return {'success': False, 'error': 'Student not found'}
        return {'success': True, 'student': student._app_detail()}

    @api.model
    def app_college_enroll_student(self, student_id, course_id, term_id):
        staff, _is_admin = college_app_staff(self.env)
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
        return {'success': True, 'student': student._app_detail()}

    # ── App API (Phase 9: public student side, no login) ─────────
    # No account exists for students, so the student code + matching email
    # together act as the lookup key. Grades only show once published —
    # a student must never see a grade before staff releases it.

    def _app_self_detail(self):
        data = self._app_summary()
        data['enrollments'] = [{
            'id': e.id, 'course_id': e.course_id.id, 'course_name': e.course_id.name,
            'term_id': e.term_id.id, 'term_name': e.term_id.name,
            'state': e.state,
            'letter_grade': e.letter_grade if e.grade_state == 'published' else '',
            'grade_pending': e.grade_state != 'published',
            'content': [{
                'id': c.id, 'name': c.name, 'content_type': c.content_type,
                'url': c.url or '', 'body': c.body or '', 'has_attachment': bool(c.attachment),
            } for c in e.course_id.content_ids],
        } for e in self.enrollment_ids]
        return data

    @api.model
    def app_college_student_lookup(self, code, email):
        code = str(code or '').strip()
        email = str(email or '').strip().lower()
        if not code or not email:
            return {'success': False, 'error': 'Enter your student number and email'}
        student = self.sudo().search([
            ('student_code', '=', code), ('email', '!=', False),
        ], limit=1).filtered(lambda s: s.email.strip().lower() == email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        return {'success': True, 'student': student._app_self_detail()}
