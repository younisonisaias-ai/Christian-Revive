from odoo import api, fields, models

from .college_app_api import public_student


class CollegeCourseContent(models.Model):
    _name = 'college.course.content'
    _description = 'Bible College Course Material'
    _order = 'course_id, sequence, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    content_type = fields.Selection([
        ('document', 'Document'),
        ('video', 'Video Link'),
        ('link', 'Link'),
        ('text', 'Text'),
    ], default='document', required=True)
    attachment = fields.Binary(attachment=True)
    attachment_filename = fields.Char()
    url = fields.Char(string='Link / Video URL')
    body = fields.Text(string='Text Content')
    active = fields.Boolean(default=True)

    # ── App API (Phase 9: public student side, no login) ─────────
    # A student may only download material for a course they are actually
    # enrolled in — re-checked here, not assumed from the app's own UI.

    @api.model
    def app_college_student_content(self, code, email, content_id):
        student = public_student(self.env, code, email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        content = self.sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.course_id.id not in enrolled_course_ids:
            return {'success': False, 'error': 'Not found'}
        if not content.attachment:
            return {'success': False, 'error': 'No file attached'}
        data = content.attachment.decode() if isinstance(content.attachment, bytes) else content.attachment
        return {'success': True, 'filename': content.attachment_filename or content.name, 'data': data}
