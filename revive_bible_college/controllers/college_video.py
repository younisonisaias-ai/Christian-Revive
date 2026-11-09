"""Video lessons kept on this server: streaming them to signed-in students,
and the staff page for uploading one or importing it from Google Drive.

Streaming goes through Odoo's own file stream, which reads from the
filestore and answers HTTP range requests, so players can seek without
downloading the whole video first."""
import json

from markupsafe import Markup

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ..models.college_app_api import token_student
from ..models.college_course_content import MAX_VIDEO_BYTES, video_mimetype

TOKEN_HEADER = 'X-College-Token'


def _json(payload, status=200):
    return request.make_response(json.dumps(payload), headers=[('Content-Type', 'application/json')], status=status)


class CollegeVideo(http.Controller):

    # ── Students ────────────────────────────────────────────────

    def _student_lesson(self, content_id, needs_file=True):
        """The video lesson, if this request's student is enrolled in its course."""
        student = token_student(request.env, request.httprequest.headers.get(TOKEN_HEADER))
        if not student:
            return None
        content = request.env['college.course.content'].sudo().browse(content_id)
        if not content.exists() or content.course_id.id not in set(student.enrollment_ids.course_id.ids):
            return None
        if content.content_type != 'video' or (needs_file and not content._app_video_fields()['has_video_file']):
            return None
        return content

    @http.route('/college/video/<int:content_id>', type='http', auth='public', methods=['GET'])
    def stream_video(self, content_id, **kwargs):
        content = self._student_lesson(content_id)
        if not content:
            return request.not_found()
        stream = request.env['ir.binary']._get_stream_from(
            content, 'video_file', filename=content.video_filename, mimetype=video_mimetype(content.video_filename))
        response = stream.get_response(as_attachment=False)
        response.headers['Cache-Control'] = 'private'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @http.route('/college/video/<int:content_id>/captions', type='http', auth='public', methods=['GET'])
    def stream_captions(self, content_id, **kwargs):
        # YouTube lessons can have captions too, shown as a transcript.
        content = self._student_lesson(content_id, needs_file=False)
        if not content or not content.caption_filename:
            return request.not_found()
        stream = request.env['ir.binary']._get_stream_from(
            content, 'caption_file', filename=content.caption_filename, mimetype='text/plain')
        response = stream.get_response(as_attachment=False)
        response.headers['Cache-Control'] = 'private'
        return response

    # ── Staff: upload page ──────────────────────────────────────

    def _staff_lesson(self, content_id):
        if not request.env.user.has_group('revive_bible_college.group_college_staff'):
            return None
        content = request.env['college.course.content'].browse(content_id).exists()
        return content if content and content.content_type == 'video' else None

    @http.route('/college/admin/lesson/<int:content_id>/video', type='http', auth='user', methods=['GET'])
    def upload_page(self, content_id, **kwargs):
        content = self._staff_lesson(content_id)
        if not content:
            return request.not_found()
        return request.render('revive_bible_college.admin_video_upload', {
            'doctype': Markup('<!DOCTYPE html>'),
            'lesson': content,
            'max_mb': MAX_VIDEO_BYTES // (1024 * 1024),
        })

    @http.route('/college/admin/lesson/<int:content_id>/video/upload', type='http', auth='user', methods=['POST'],
                csrf=True, max_content_length=MAX_VIDEO_BYTES + 16 * 1024 * 1024)
    def upload_video(self, content_id, **kwargs):
        content = self._staff_lesson(content_id)
        if not content:
            return _json({'ok': False, 'error': 'You do not have access to this lesson.'}, 403)
        upload = request.httprequest.files.get('video')
        if not upload or not upload.filename:
            return _json({'ok': False, 'error': 'Choose a video file first.'}, 400)
        try:
            content._set_video_file(upload.read(), upload.filename, 'upload')
        except UserError as error:
            return _json({'ok': False, 'error': str(error)}, 400)
        return _json({'ok': True, 'filename': content.video_filename, 'size': content.video_size_label})

    @http.route('/college/admin/lesson/<int:content_id>/video/drive', type='http', auth='user', methods=['POST'], csrf=True)
    def import_drive(self, content_id, drive_url='', **kwargs):
        content = self._staff_lesson(content_id)
        if not content:
            return _json({'ok': False, 'error': 'You do not have access to this lesson.'}, 403)
        try:
            content._import_from_drive(drive_url.strip())
        except UserError as error:
            return _json({'ok': False, 'error': str(error)}, 400)
        return _json({'ok': True, 'filename': content.video_filename, 'size': content.video_size_label})
