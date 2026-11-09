import os
import re
from io import BytesIO
from urllib.parse import unquote

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .college_app_api import public_student, token_student

MAX_VIDEO_BYTES = 1024 * 1024 * 1024
VIDEO_EXTENSIONS = {'.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm'}
CAPTION_EXTENSIONS = ('.vtt', '.srt')
_DRIVE_ID_RE = re.compile(r'(?:/file/d/|[?&]id=|/d/)([A-Za-z0-9_-]{10,})')
_DISPOSITION_RE = re.compile(r"filename\*=UTF-8''([^;]+)|filename=\"?([^\";]+)\"?", re.I)


def drive_file_id(url):
    """The file id from any common Google Drive share link, or None."""
    match = _DRIVE_ID_RE.search(url or '')
    return match.group(1) if match else None


def video_mimetype(filename):
    """The video mimetype for a supported file name, or None."""
    return VIDEO_EXTENSIONS.get(os.path.splitext((filename or '').lower())[1])


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
        ('video', 'Video'),
        ('link', 'Link'),
        ('text', 'Text'),
        ('quiz', 'Quiz'),
        ('flashcards', 'Flashcards'),
    ], default='document', required=True)
    attachment = fields.Binary(attachment=True)
    attachment_filename = fields.Char()
    url = fields.Char(string='Link / Video URL')
    body = fields.Text(string='Text Content')
    quiz_id = fields.Many2one('college.quiz', string='Quiz')
    deck_id = fields.Many2one('college.flashcard.deck', string='Flashcard Deck')
    active = fields.Boolean(default=True)

    # Video lessons: a YouTube link (url), or a file kept on this server,
    # either uploaded from a computer or copied in from a Google Drive link.
    # The file is only ever written through _set_video_file (see the upload
    # page in controllers/college_video.py), never through the form, since a
    # form save sends the whole file inside one JSON request.
    video_source = fields.Selection([
        ('youtube', 'YouTube link'),
        ('upload', 'Upload from computer'),
        ('drive', 'Google Drive link'),
    ], default='youtube')  # Not required: a blank (older rows) means YouTube.
    video_file = fields.Binary(attachment=True, readonly=True)
    video_filename = fields.Char(readonly=True)
    # Stored so listing lessons never has to read the video itself.
    video_size = fields.Integer(readonly=True)
    video_size_label = fields.Char(compute='_compute_video_size_label', string='File size')
    drive_url = fields.Char(string='Google Drive link', readonly=True)
    caption_file = fields.Binary(attachment=True, string='Captions (.vtt or .srt)')
    caption_filename = fields.Char()

    @api.depends('video_size')
    def _compute_video_size_label(self):
        for lesson in self:
            size = lesson.video_size or 0
            lesson.video_size_label = '%.0f MB' % (size / 1048576) if size >= 1048576 else ('%d KB' % (size // 1024) if size else '')

    @api.constrains('caption_filename')
    def _check_caption_filename(self):
        for lesson in self:
            if lesson.caption_filename and not lesson.caption_filename.lower().endswith(CAPTION_EXTENSIONS):
                raise ValidationError(_('Captions must be a .vtt or .srt file.'))

    def action_open_lesson(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'college.course.content',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_video_upload(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/college/admin/lesson/%d/video' % self.id, 'target': 'new'}

    def action_remove_video_file(self):
        for lesson in self:
            lesson._video_attachment().unlink()
            lesson.write({'video_size': 0, 'video_filename': False, 'drive_url': False})

    def _video_attachment(self):
        self.ensure_one()
        return self.env['ir.attachment'].sudo().search([
            ('res_model', '=', self._name), ('res_field', '=', 'video_file'), ('res_id', '=', self.id),
        ])

    def _set_video_file(self, raw, filename, source, drive_url=False):
        """Store a video directly as the field's attachment from raw bytes,
        so a large file isn't held a second time as base64."""
        self.ensure_one()
        mimetype = video_mimetype(filename)
        if not mimetype:
            raise UserError(_('Use an MP4, MOV or WebM video file.'))
        if not raw:
            raise UserError(_('That file is empty.'))
        if len(raw) > MAX_VIDEO_BYTES:
            raise UserError(_('That video is larger than 1 GB. Compress it (720p MP4 works well) and try again.'))
        self._video_attachment().unlink()
        self.env['ir.attachment'].sudo().create({
            'name': filename, 'raw': raw, 'mimetype': mimetype,
            'res_model': self._name, 'res_field': 'video_file', 'res_id': self.id,
        })
        self.write({
            'content_type': 'video', 'video_source': source, 'video_filename': filename,
            'video_size': len(raw), 'drive_url': drive_url,
        })

    def _import_from_drive(self, url):
        """Copy a publicly shared Google Drive video onto this server."""
        self.ensure_one()
        file_id = drive_file_id(url)
        if not file_id:
            raise UserError(_('That doesn\'t look like a Google Drive file link.'))
        try:
            response = requests.get(
                'https://drive.usercontent.google.com/download',
                params={'id': file_id, 'export': 'download', 'confirm': 't'},
                stream=True, timeout=(10, 120),
            )
        except requests.RequestException:
            raise UserError(_('Could not reach Google Drive. Check the server\'s internet connection and try again.'))
        with response:
            content_type = response.headers.get('Content-Type', '')
            if response.status_code != 200 or content_type.startswith('text/html'):
                raise UserError(_('Google Drive did not hand over the video. Make sure it is shared as "Anyone with the link".'))
            match = _DISPOSITION_RE.search(response.headers.get('Content-Disposition', ''))
            filename = unquote(match.group(1) or match.group(2)).strip() if match else 'video'
            if not video_mimetype(filename):
                extension = next((ext for ext, mime in VIDEO_EXTENSIONS.items() if content_type.startswith(mime)), None)
                if extension:
                    filename += extension
            buffer = BytesIO()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                buffer.write(chunk)
                if buffer.tell() > MAX_VIDEO_BYTES:
                    raise UserError(_('That video is larger than 1 GB. Compress it (720p MP4 works well) and try again.'))
        self._set_video_file(buffer.getvalue(), filename, 'drive', drive_url=url)

    def _app_video_fields(self):
        """What the app needs to pick a player for this lesson."""
        self.ensure_one()
        source = self.video_source or 'youtube'
        has_file = self.content_type == 'video' and source != 'youtube' and self.video_size > 0
        return {
            'video_source': source if self.content_type == 'video' else '',
            'has_video_file': has_file,
            'has_captions': has_file and bool(self.caption_filename),
        }

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
