from odoo import api, fields, models

from .college_app_api import token_student

MAX_NOTE_LENGTH = 2000


class CollegeLessonNote(models.Model):
    """A student's own note or bookmark at a moment in a video lesson.

    Private to the student, like a personal notebook: no college staff or
    admin group can read these, only the student through the app (and the
    ERP's technical administrators, for data upkeep). A bookmark is simply
    a note with no text."""
    _name = 'college.lesson.note'
    _description = "A student's video note or bookmark"
    _order = 'position, id'
    _rec_name = 'content_id'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    content_id = fields.Many2one('college.course.content', required=True, ondelete='cascade', index=True)
    position = fields.Float(string='Video time (seconds)', default=0.0)
    body = fields.Text()

    def _app_payload(self):
        return [{'id': n.id, 'position': n.position, 'body': n.body or ''} for n in self]

    @api.model
    def _student_and_lesson(self, token, content_id):
        student = token_student(self.env, token)
        if not student:
            return None, None, {'success': False, 'error': 'Please sign in again'}
        content = self.env['college.course.content'].sudo().browse(content_id)
        if not content.exists() or content.course_id.id not in set(student.enrollment_ids.course_id.ids):
            return None, None, {'success': False, 'error': 'Not found'}
        return student, content, None

    @api.model
    def app_college_my_notes(self, token, content_id):
        student, content, error = self._student_and_lesson(token, content_id)
        if error:
            return error
        notes = self.sudo().search([('student_id', '=', student.id), ('content_id', '=', content.id)])
        return {'success': True, 'notes': notes._app_payload()}

    @api.model
    def app_college_my_note_save(self, token, content_id, position, body='', note_id=None):
        """Adds a note (no note_id) or changes one of the student's own."""
        student, content, error = self._student_and_lesson(token, content_id)
        if error:
            return error
        body = (body or '').strip()
        if len(body) > MAX_NOTE_LENGTH:
            return {'success': False, 'error': 'That note is too long. Keep it under %d characters.' % MAX_NOTE_LENGTH}
        vals = {'position': max(0.0, float(position or 0)), 'body': body or False}
        if note_id:
            note = self.sudo().search([
                ('id', '=', int(note_id)), ('student_id', '=', student.id), ('content_id', '=', content.id),
            ])
            if not note:
                return {'success': False, 'error': 'Not found'}
            note.write(vals)
        else:
            note = self.sudo().create({**vals, 'student_id': student.id, 'content_id': content.id})
        return {'success': True, 'note': note._app_payload()[0]}

    @api.model
    def app_college_my_note_delete(self, token, note_id):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        note = self.sudo().search([('id', '=', int(note_id)), ('student_id', '=', student.id)])
        if not note:
            return {'success': False, 'error': 'Not found'}
        note.unlink()
        return {'success': True}
