"""Student pages at /college: the same account and data as the phone app, in a
browser. Plain pages (no website module needed), like the medical camp's
referral page."""
import base64

from markupsafe import Markup

from odoo import http
from odoo.http import request

from ..models.college_app_api import token_student

COOKIE = 'college_session'
COOKIE_DAYS = 90
MAX_UPLOAD = 5 * 1024 * 1024


def _render(template, values=None, status=200):
    values = dict(values or {}, doctype=Markup('<!DOCTYPE html>'))
    resp = request.render('revive_bible_college.%s' % template, values, status=status)
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


def _is_https():
    forwarded = request.httprequest.headers.get('X-Forwarded-Proto', '')
    return request.httprequest.scheme == 'https' or forwarded.split(',')[0].strip() == 'https'


def _signed_in(token):
    resp = request.redirect('/college/home', local=True)
    resp.set_cookie(COOKIE, token, max_age=COOKIE_DAYS * 86400, path='/college',
                    httponly=True, samesite='Lax', secure=_is_https())
    return resp


def _web_link(url):
    url = (url or '').strip()
    return url if url.lower().startswith(('http://', 'https://')) else ''


class CollegePortal(http.Controller):

    def _token(self):
        return request.httprequest.cookies.get(COOKIE)

    def _student(self):
        return token_student(request.env, self._token())

    def _to_sign_in(self):
        return request.redirect('/college', local=True)

    @http.route('/college', type='http', auth='public', methods=['GET', 'POST'], csrf=True)
    def sign_in(self, code='', password='', **kwargs):
        if request.httprequest.method == 'GET':
            if self._student():
                return request.redirect('/college/home', local=True)
            return _render('portal_sign_in')
        result = request.env['college.student'].app_college_student_sign_in(code, password, device_id='web')
        if result.get('success'):
            return _signed_in(result['session_token'])
        return _render('portal_sign_in', {'code': code, 'error': result.get('error')})

    @http.route('/college/first-time', type='http', auth='public', methods=['GET', 'POST'], csrf=True)
    def first_time(self, code='', signin_code='', password='', confirm='', **kwargs):
        if request.httprequest.method == 'GET':
            return _render('portal_first_time')
        values = {'code': code, 'signin_code': signin_code}
        if password != confirm:
            return _render('portal_first_time', dict(values, error='The two passwords do not match'))
        result = request.env['college.student'].app_college_student_activate(
            code, signin_code, password, device_id='web')
        if result.get('success'):
            return _signed_in(result['session_token'])
        return _render('portal_first_time', dict(values, error=result.get('error')))

    @http.route('/college/sign-out', type='http', auth='public', methods=['POST'], csrf=True)
    def sign_out(self, **kwargs):
        request.env['college.student'].app_college_student_sign_out(self._token())
        resp = self._to_sign_in()
        resp.delete_cookie(COOKIE, path='/college')
        return resp

    @http.route('/college/home', type='http', auth='public', methods=['GET'])
    def home(self, **kwargs):
        student = self._student()
        if not student:
            return self._to_sign_in()
        assignments = request.env['college.assignment']._student_assignments(student)
        return _render('portal_home', {
            'student': student._app_self_detail(),
            'to_do': [a for a in assignments if a['submission_state'] in ('none', 'draft')],
            'done': [a for a in assignments if a['submission_state'] not in ('none', 'draft')],
        })

    @http.route('/college/course/<int:enrollment_id>', type='http', auth='public', methods=['GET'])
    def course(self, enrollment_id, **kwargs):
        student = self._student()
        if not student:
            return self._to_sign_in()
        enrollment = next((e for e in student._app_self_detail()['enrollments'] if e['id'] == enrollment_id), None)
        if not enrollment:
            return request.not_found()
        for item in enrollment['content']:
            item['url'] = _web_link(item['url'])
        return _render('portal_course', {'enrollment': enrollment})

    @http.route('/college/file/<int:content_id>', type='http', auth='public', methods=['GET'])
    def file(self, content_id, **kwargs):
        student = self._student()
        if not student:
            return self._to_sign_in()
        result = request.env['college.course.content']._student_file(student, content_id)
        if not result.get('success'):
            return request.not_found()
        name = result['filename'].replace('"', '').replace('\r', '').replace('\n', '')
        return request.make_response(base64.b64decode(result['data']), headers=[
            ('Content-Type', 'application/octet-stream'),
            ('Content-Disposition', 'attachment; filename="%s"' % name),
            ('X-Content-Type-Options', 'nosniff'),
            ('Cache-Control', 'no-store'),
        ])

    @http.route('/college/assignment/<int:assignment_id>', type='http', auth='public',
                methods=['GET', 'POST'], csrf=True)
    def assignment(self, assignment_id, text_answer='', **kwargs):
        student = self._student()
        if not student:
            return self._to_sign_in()
        Assignment = request.env['college.assignment']
        rows = Assignment._student_assignments(student)
        row = next((a for a in rows if a['id'] == assignment_id), None)
        if not row:
            return request.not_found()
        if request.httprequest.method == 'GET':
            return _render('portal_assignment', {'a': row})
        upload = request.httprequest.files.get('attachment')
        data = upload.read(MAX_UPLOAD + 1) if upload and upload.filename else b''
        if len(data) > MAX_UPLOAD:
            return _render('portal_assignment', {'a': row, 'answer': text_answer,
                                                 'error': 'That file is too large. Choose a file under 5 MB.'})
        result = Assignment._student_submit(student, assignment_id, text_answer=text_answer,
                                            attachment=base64.b64encode(data).decode() if data else None,
                                            attachment_filename=upload.filename if data else '')
        if not result.get('success'):
            return _render('portal_assignment', {'a': row, 'answer': text_answer, 'error': result.get('error')})
        return request.redirect('/college/home', local=True)

    @http.route('/college/certificate', type='http', auth='public', methods=['GET'])
    def verify_certificate(self, code='', **kwargs):
        checked = bool(code.strip())
        certificate = None
        if checked:
            result = request.env['college.certificate'].app_college_verify_certificate(code)
            certificate = result['certificate'] if result.get('success') else None
        return _render('portal_certificate', {'code': code, 'checked': checked, 'certificate': certificate})
