from odoo import api, fields, models

from .college_app_api import token_student


class CollegeLessonProgress(models.Model):
    """One student's progress on one lesson: whether they have started or
    finished it, and, for a video, where to resume. Rows are created lazily,
    the first time a student opens or completes a lesson."""
    _name = 'college.lesson.progress'
    _description = "A student's lesson progress"
    _order = 'id desc'
    _rec_name = 'content_id'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    content_id = fields.Many2one('college.course.content', required=True, ondelete='cascade', index=True)
    started = fields.Boolean(default=True)
    completed = fields.Boolean(default=False)
    completed_date = fields.Datetime(readonly=True)
    video_position = fields.Float(string='Video Position (seconds)', default=0.0)

    _student_content_uniq = models.Constraint(
        'unique(student_id, content_id)', 'Already have a progress record for this lesson.')

    @api.model
    def app_college_my_progress_save(self, token, content_id, video_position=None, completed=None):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self.env['college.course.content'].sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.course_id.id not in enrolled_course_ids:
            return {'success': False, 'error': 'Not found'}
        progress = self.sudo().search([('student_id', '=', student.id), ('content_id', '=', content_id)], limit=1)
        vals = {'started': True}
        if video_position is not None:
            vals['video_position'] = max(0.0, float(video_position))
        if completed is not None:
            vals['completed'] = bool(completed)
            vals['completed_date'] = fields.Datetime.now() if completed else False
        if progress:
            progress.write(vals)
        else:
            vals.update({'student_id': student.id, 'content_id': content_id})
            self.sudo().create(vals)
        return {'success': True}
