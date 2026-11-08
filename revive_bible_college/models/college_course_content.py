from odoo import api, fields, models

from .college_app_api import public_student, token_student


class CollegeCourseContent(models.Model):
    """One lesson within a course module: a document, a video link, a
    plain link, or a text reading. "Course Material" was this model's
    original name, kept so it never needed a rename; students see it as
    a Lesson (see college.course.module, added for the modules/lessons
    structure and per-student progress)."""
    _name = 'college.course.content'
    _description = 'Bible College Course Material'
    _order = 'course_id, sequence, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True, ondelete='cascade')
    # Not required at the field level: existing rows are backfilled by the
    # 19.0.1.12.0 migration rather than blocking the upgrade on a NOT NULL
    # column. New lessons always get one, created from inside a module.
    module_id = fields.Many2one('college.course.module', ondelete='cascade')
    sequence = fields.Integer(default=10)
    content_type = fields.Selection([
        ('document', 'Document'),
        ('video', 'Video Link'),
        ('link', 'Link'),
        ('text', 'Text'),
        ('quiz', 'Quiz'),
    ], default='document', required=True)
    attachment = fields.Binary(attachment=True)
    attachment_filename = fields.Char()
    url = fields.Char(string='Link / Video URL')
    body = fields.Text(string='Text Content')
    quiz_id = fields.Many2one('college.quiz', string='Quiz')
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        # A lesson added from inside a module (the normal path) names only
        # the module; take its course from there so staff never has to
        # pick the same course twice.
        for vals in vals_list:
            if vals.get('module_id') and not vals.get('course_id'):
                vals['course_id'] = self.env['college.course.module'].browse(vals['module_id']).course_id.id
        return super().create(vals_list)

    # ── App API (Phase 9: public student side, no login) ─────────
    # A student may only download material for a course they are actually
    # enrolled in — re-checked here, not assumed from the app's own UI.

    @api.model
    def app_college_student_content(self, code, email, content_id):
        student = public_student(self.env, code, email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        return self._student_file(student, content_id)

    @api.model
    def app_college_my_content(self, token, content_id):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        return self._student_file(student, content_id)

    @api.model
    def _student_file(self, student, content_id):
        content = self.sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.course_id.id not in enrolled_course_ids:
            return {'success': False, 'error': 'Not found'}
        if not content.attachment:
            return {'success': False, 'error': 'No file attached'}
        data = content.attachment.decode() if isinstance(content.attachment, bytes) else content.attachment
        return {'success': True, 'filename': content.attachment_filename or content.name, 'data': data}
