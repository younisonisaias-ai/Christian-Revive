import re
import secrets

from odoo import api, fields, models

from .college_app_api import token_student
from .college_student_auth import CODE_LETTERS

_CODE_GROUP_SIZE = 4
_CODE_GROUPS = 4


class CollegeCertificate(models.Model):
    """A course-completion certificate, issued automatically the first time
    a student with every lesson in a course marked done asks to see it —
    staff never generate these by hand. Permanent once issued: a lesson
    being un-marked afterward does not revoke it, the same "once complete,
    stays complete" rule used for lesson/quiz/flashcard progress."""
    _name = 'college.certificate'
    _description = 'Bible College Certificate'
    _order = 'issued_date desc'
    _rec_name = 'verification_code'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    enrollment_id = fields.Many2one('college.enrollment', required=True, ondelete='cascade', index=True)
    verification_code = fields.Char(required=True, readonly=True, copy=False, index=True,
                                     help='A permanent code anyone can check at /college/certificate — '
                                          'not a secret, just proof this certificate is real.')
    issued_date = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    _student_enrollment_uniq = models.Constraint(
        'unique(student_id, enrollment_id)', 'A certificate has already been issued for this enrollment.')
    _verification_code_uniq = models.Constraint('unique(verification_code)', 'Verification code must be unique.')

    @api.model
    def _new_verification_code(self):
        for _attempt in range(10):
            code = ''.join(secrets.choice(CODE_LETTERS) for _ in range(_CODE_GROUP_SIZE * _CODE_GROUPS))
            if not self.sudo().search_count([('verification_code', '=', code)]):
                return code
        raise ValueError('Could not generate a unique verification code')

    def _display_code(self):
        self.ensure_one()
        code = self.verification_code or ''
        return '-'.join(code[i:i + _CODE_GROUP_SIZE] for i in range(0, len(code), _CODE_GROUP_SIZE))

    def _app_payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'verification_code': self._display_code(),
            'issued_date': self.issued_date.isoformat() if self.issued_date else '',
            'student_name': self.student_id.name,
            'course_name': self.enrollment_id.course_id.name,
            'program_name': self.student_id.program_id.name,
            'term_name': self.enrollment_id.term_id.name,
        }

    @api.model
    def _enrollment_progress(self, enrollment):
        total = len(enrollment.course_id.content_ids)
        if not total:
            return 0, 0
        done = self.env['college.lesson.progress'].sudo().search_count([
            ('student_id', '=', enrollment.student_id.id),
            ('content_id.course_id', '=', enrollment.course_id.id),
            ('completed', '=', True),
        ])
        return total, done

    @api.model
    def _issue(self, student, enrollment):
        existing = self.sudo().search([
            ('student_id', '=', student.id), ('enrollment_id', '=', enrollment.id),
        ], limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'student_id': student.id, 'enrollment_id': enrollment.id,
            'verification_code': self._new_verification_code(),
        })

    # ── App API (student's own view, token-only) ──────────────────

    @api.model
    def app_college_my_certificate(self, token, enrollment_id):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        enrollment = student.enrollment_ids.filtered(lambda e: e.id == enrollment_id)
        if not enrollment:
            return {'success': False, 'error': 'Not found'}
        # Once issued, a certificate stays fetchable even if a lesson is
        # later marked undone again — the eligibility check below only
        # ever gates ISSUING a new one, never an already-earned one.
        certificate = self.sudo().search([
            ('student_id', '=', student.id), ('enrollment_id', '=', enrollment.id),
        ], limit=1)
        if not certificate:
            total, done = self._enrollment_progress(enrollment)
            if not total or done < total:
                return {'success': False, 'error': 'Complete every lesson in this course first.'}
            certificate = self._issue(student, enrollment)
        return {'success': True, 'certificate': certificate._app_payload()}

    # ── Public verification (no sign-in — anyone holding the code) ─

    @api.model
    def app_college_verify_certificate(self, code):
        clean = re.sub(r'[^A-Z0-9]', '', str(code or '').upper())
        if not clean:
            return {'success': False, 'error': 'Enter a verification code'}
        certificate = self.sudo().search([('verification_code', '=', clean)], limit=1)
        if not certificate:
            return {'success': False, 'error': 'No certificate found with that code'}
        return {'success': True, 'certificate': certificate._app_payload()}
