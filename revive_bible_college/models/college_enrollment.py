from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .college_app_api import college_app_staff

# Standard letter scale, used only as the starting suggestion — staff can
# always type over the computed letter for a course with its own scale.
GRADE_SCALE = [
    (90, 'A'), (85, 'A-'), (80, 'B+'), (75, 'B'), (70, 'B-'),
    (65, 'C+'), (60, 'C'), (50, 'D'),
]
GRADE_POINTS = {
    'A': 4.0, 'A-': 3.7, 'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'D': 1.0, 'F': 0.0,
}


class CollegeEnrollment(models.Model):
    _name = 'college.enrollment'
    _description = 'Bible College Course Enrollment'
    _order = 'id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    course_id = fields.Many2one('college.course', required=True)
    term_id = fields.Many2one('college.term', required=True)
    state = fields.Selection([
        ('enrolled', 'Enrolled'),
        ('completed', 'Completed'),
        ('withdrawn', 'Withdrawn'),
    ], default='enrolled', required=True)

    grade_state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('published', 'Published'),
    ], default='draft', required=True)
    numeric_grade = fields.Float(string='Score (0-100)')
    letter_grade = fields.Char(compute='_compute_letter_grade', store=True, readonly=False,
                                help='Suggested from the score; staff can type over it.')
    credits_earned = fields.Float(compute='_compute_credits_earned', store=True)
    graded_by = fields.Many2one('res.users', readonly=True, copy=False)
    graded_date = fields.Date(readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Date(readonly=True, copy=False)
    published_date = fields.Date(readonly=True, copy=False)

    _student_course_term_uniq = models.Constraint(
        'unique(student_id, course_id, term_id)',
        'This student is already enrolled in this course for this term.',
    )

    @api.depends('numeric_grade')
    def _compute_letter_grade(self):
        for enrollment in self:
            # A score of 0 counts as no score here; a real zero is typed as F.
            if not enrollment.numeric_grade:
                enrollment.letter_grade = False
                continue
            letter = 'F'
            for minimum, label in GRADE_SCALE:
                if enrollment.numeric_grade >= minimum:
                    letter = label
                    break
            enrollment.letter_grade = letter

    @api.depends('student_id.name', 'course_id.name')
    def _compute_display_name(self):
        for enrollment in self:
            enrollment.display_name = '%s, %s' % (enrollment.student_id.name or '', enrollment.course_id.name or '')

    @api.depends('grade_state', 'course_id.credits')
    def _compute_credits_earned(self):
        for enrollment in self:
            enrollment.credits_earned = enrollment.course_id.credits if enrollment.grade_state == 'published' else 0.0

    def _require_admin(self):
        if not self.env.user.has_group('revive_bible_college.group_college_admin'):
            raise UserError(_('Only a Bible College admin can do this.'))

    def action_submit_grade(self):
        self._do_submit_grade(self.env.user)

    def action_approve_grade(self):
        self._require_admin()
        self._do_approve_grade(self.env.user)

    def action_publish_grade(self):
        self._require_admin()
        self._do_publish_grade()

    def action_reset_to_draft(self):
        self._require_admin()
        self._do_reset_grade()

    # The app checks the signed-in staff member's role itself, because every
    # phone reaches the server through one shared ERP account.

    def _do_submit_grade(self, user):
        for enrollment in self:
            if enrollment.grade_state != 'draft':
                continue
            if not enrollment.numeric_grade and not enrollment.letter_grade:
                raise UserError(_('Enter a score or letter grade for %s first.', enrollment.display_name))
            enrollment.write({
                'grade_state': 'submitted',
                'graded_by': user.id,
                'graded_date': fields.Date.context_today(self),
            })

    def _do_approve_grade(self, user):
        for enrollment in self:
            if enrollment.grade_state != 'submitted':
                continue
            enrollment.write({
                'grade_state': 'approved',
                'approved_by': user.id,
                'approved_date': fields.Date.context_today(self),
            })

    def _do_publish_grade(self):
        for enrollment in self:
            if enrollment.grade_state != 'approved':
                continue
            enrollment.write({
                'grade_state': 'published',
                'published_date': fields.Date.context_today(self),
                'state': 'completed',
            })

    def _do_reset_grade(self):
        self.write({
            'grade_state': 'draft',
            'graded_by': False, 'graded_date': False,
            'approved_by': False, 'approved_date': False, 'published_date': False,
        })

    @api.model
    def app_college_grade_action(self, enrollment_id, action, numeric_grade=None):
        staff, is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        enrollment = self.sudo().browse(enrollment_id)
        if not enrollment.exists():
            return {'success': False, 'error': 'Course not found'}
        user = staff.user_id or self.env.user
        if action == 'submit':
            if enrollment.grade_state != 'draft':
                return {'success': False, 'error': 'This grade was already submitted'}
            if numeric_grade is not None:
                if not isinstance(numeric_grade, (int, float)) or not 0 <= numeric_grade <= 100:
                    return {'success': False, 'error': 'Enter a score from 0 to 100'}
                enrollment.numeric_grade = numeric_grade
            if not enrollment.numeric_grade and not enrollment.letter_grade:
                return {'success': False, 'error': 'Enter a score first'}
            enrollment._do_submit_grade(user)
        elif action in ('approve', 'publish', 'reset'):
            if not is_admin:
                return {'success': False, 'error': 'Only a Bible College admin can do this.'}
            if action == 'approve':
                if enrollment.grade_state != 'submitted':
                    return {'success': False, 'error': 'This grade is not waiting for approval'}
                enrollment._do_approve_grade(user)
            elif action == 'publish':
                if enrollment.grade_state != 'approved':
                    return {'success': False, 'error': 'Approve this grade first'}
                enrollment._do_publish_grade()
            else:
                enrollment._do_reset_grade()
        else:
            return {'success': False, 'error': 'Unknown action'}
        return {'success': True, 'student': enrollment.student_id._app_detail(is_admin)}
