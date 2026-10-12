"""Camp Mode API for the mobile app: /api/camp/...

Each camp worker signs in with their OWN Odoo login: an internal user with a
camp role, or a portal user (free) who is on a camp team. The phone receives an
API key that only works for this camp API (scope "revive_camp"), expires
after 30 days and is deleted on logout. All other calls send it as
``Authorization: Bearer <key>`` and run as that worker, so their camp role
decides what they can see and do.

Requests and responses are JSON. Errors: {"error": {"code": ..., "message": ...}}
with HTTP 400 (bad request), 401 (not signed in), 403 (not allowed),
404 (not found) or 500.
"""
import functools
import logging
import re
from datetime import datetime, timedelta

from odoo import http
from odoo.addons.base.models.res_users import INDEX_SIZE, KEY_CRYPT_CONTEXT
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

API_SCOPE = 'revive_camp'
KEY_DAYS = 30


def _json(data, status=200):
    return request.make_json_response(data, status=status)


def _error(code, message, status):
    return _json({'error': {'code': code, 'message': message}}, status=status)


def _bearer_token():
    header = request.httprequest.headers.get('Authorization') or ''
    match = re.match(r'^bearer\s+(\S+)$', header, re.IGNORECASE)
    return match.group(1) if match else None


def _body():
    try:
        return request.get_json_data() or {}
    except ValueError:
        raise UserError('The request body must be JSON.')  # noqa: B904


def _ip():
    return request.httprequest.remote_addr or '?'


def camp_route(route, methods, password_change=False):
    """A JSON route that needs a camp API key and turns errors into JSON."""
    def decorator(func):
        @http.route(route, type='http', auth='public', methods=methods, csrf=False, save_session=False)
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            token = _bearer_token()
            uid = None
            if token:
                uid = request.env['res.users.apikeys'].sudo()._check_credentials(scope=API_SCOPE, key=token)
            if not uid:
                if token and request.env['camp.revoked.key'].sudo().search_count([('index', '=', token[:INDEX_SIZE])]):
                    # Signed out from Odoo (lost phone): the phone deletes its camp data.
                    return _error('wiped', 'This phone was signed out by the camp coordinator.', 401)
                return _error('unauthorized', 'Sign in again (missing or expired key).', 401)
            request.update_env(user=uid)
            if not password_change and request.env.user.camp_must_change_password:
                return _error('password_change_required', 'Choose a new password first.', 403)
            if not request.env['camp.api']._is_camp_worker():
                return _error('forbidden', 'This login has no medical camp role.', 403)
            return _call(func, self, *args, **kwargs)
        return wrapper
    return decorator


def _call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except AccessDenied as e:
        return _error('unauthorized', str(e) or 'Access denied', 401)
    except AccessError as e:
        return _error('forbidden', str(e.args[0] if e.args else e), 403)
    except MissingError as e:
        return _error('not_found', str(e.args[0] if e.args else e), 404)
    except (UserError, ValidationError, ValueError) as e:
        return _error('bad_request', str(e.args[0] if e.args else e), 400)
    except Exception:
        _logger.exception('Camp API error')
        return _error('server_error', 'Something went wrong on the server.', 500)


class CampApiController(http.Controller):

    # ── Sign in / out ──────────────────────────────────────────
    @http.route('/api/camp/login', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def login(self, **kwargs):
        def _do():
            body = _body()
            login, password = (body.get('login') or '').strip(), body.get('password') or ''
            if not login or not password:
                raise UserError('Enter your login and password.')
            Throttle, Captcha = request.env['camp.auth.throttle'], request.env['camp.captcha']
            keys = [f'login:{login.lower()}', f'ip:{_ip()}']
            locked, need_captcha = Throttle.status(keys)
            if locked:
                return _error('locked', f'Too many wrong passwords. Try again in {locked} minutes.', 429)
            if need_captcha and not Captcha.check(body.get('captcha_token'), body.get('captcha_answer')):
                # After 3 wrong passwords: prove a person is typing.
                token, image = Captcha.new()
                return _json({'error': {'code': 'captcha_required',
                                        'message': 'Type the numbers in the picture.' if not body.get('captcha_token')
                                        else 'The numbers did not match. Try the new picture.',
                                        'captcha_token': token, 'captcha_image': image}}, status=401)
            # Workers may type their login, email or phone number. Several
            # users can match (e.g. an old office user with the same email):
            # the password decides which one it is, camp workers first.
            user, not_worker = None, None
            for candidate in request.env['camp.api'].sudo()._login_candidates(login):
                credential = {'type': 'password', 'login': candidate, 'password': password}
                try:
                    auth = request.env['res.users'].sudo().authenticate(
                        credential, {'interactive': False, 'base_location': request.httprequest.url_root})
                except AccessDenied:
                    continue
                found = request.env['res.users'].sudo().browse(auth['uid'])
                if request.env['camp.api'].with_user(found)._is_camp_worker():
                    user = found
                    break
                not_worker = not_worker or found
            if not user and not_worker:
                return _error('forbidden', 'This login has no medical camp role. Ask your camp coordinator.', 403)
            if not user:
                Throttle.failed(keys, lock_key=keys[0])
                request.env['camp.audit.log'].sudo().log('sign_in_failed', details=f'login {login[:60]}',
                                                         user=request.env.ref('base.public_user'))
                locked, need_captcha = Throttle.status(keys)
                if locked:
                    return _error('locked', f'Too many wrong passwords. Try again in {locked} minutes.', 429)
                return _error('unauthorized', 'Wrong login or password.', 401)
            Throttle.succeeded(keys)
            if user._mfa_url():
                return _error('mfa_not_supported',
                              'This login uses two-step verification, which Camp Mode does not support yet. '
                              'Use a separate camp login.', 403)
            device = (body.get('device_name') or 'phone')[:60]
            key = request.env['res.users.apikeys'].with_user(user).sudo()._generate(
                API_SCOPE, f'Camp Mode: {device}', datetime.now() + timedelta(days=KEY_DAYS))
            request.update_env(user=user.id)
            request.env['camp.audit.log'].log('sign_in', details=f'Camp Mode: {device}')
            data = request.env['camp.api'].me()
            data.update({'token': key, 'expires_in_days': KEY_DAYS})
            return _json(data)
        return _call(_do)

    @camp_route('/api/camp/password', ['POST'], password_change=True)
    def change_password(self, **kwargs):
        """First sign-in: replace the one-time password from the coordinator."""
        def _do():
            from ..models.camp_security import password_problem
            body = _body()
            old, new = body.get('old_password') or '', body.get('new_password') or ''
            user = request.env.user
            problem = password_problem(new, user.login)
            if problem:
                raise UserError(problem)
            if new == old:
                raise UserError('Choose a password different from the one you were given.')
            try:
                user._check_credentials({'type': 'password', 'password': old}, {'interactive': False})
            except AccessDenied:
                return _error('unauthorized', 'The current password is wrong.', 401)
            user.sudo()._change_password(new)
            user.sudo().camp_must_change_password = False
            return _json({'ok': True})
        return _call(_do)

    @camp_route('/api/camp/logout', ['POST'], password_change=True)
    def logout(self, **kwargs):
        token = _bearer_token()
        Keys = request.env['res.users.apikeys'].sudo()
        request.env.cr.execute(
            'SELECT id, key FROM res_users_apikeys WHERE index = %s AND scope = %s AND user_id = %s',
            (token[:INDEX_SIZE], API_SCOPE, request.env.uid))
        for key_id, hashed in request.env.cr.fetchall():
            if KEY_CRYPT_CONTEXT.verify(token, hashed):
                Keys.browse(key_id)._remove()
        return _json({'ok': True})

    # ── Read ───────────────────────────────────────────────────
    @camp_route('/api/camp/me', ['GET'])
    def me(self, **kwargs):
        return _json(request.env['camp.api'].me())

    @camp_route('/api/camp/<int:camp_id>/bootstrap', ['GET'])
    def bootstrap(self, camp_id, reserve_tokens='0', **kwargs):
        return _json(request.env['camp.api'].bootstrap(camp_id, reserve_tokens=int(reserve_tokens or 0)))

    @camp_route('/api/camp/<int:camp_id>/changes', ['GET'])
    def changes(self, camp_id, since=None, **kwargs):
        return _json(request.env['camp.api'].changes(camp_id, since=since or None))

    @camp_route('/api/camp/<int:camp_id>/queue/<string:station>', ['GET'])
    def queue(self, camp_id, station, **kwargs):
        return _json(request.env['camp.api'].queue(camp_id, station))

    @camp_route('/api/camp/<int:camp_id>/status', ['GET'])
    def status(self, camp_id, **kwargs):
        return _json(request.env['camp.api'].camp_status(camp_id))

    @camp_route('/api/camp/<int:camp_id>/summary', ['GET'])
    def summary(self, camp_id, **kwargs):
        return _json(request.env['camp.api'].camp_summary(camp_id))

    @camp_route('/api/camp/patients', ['GET'])
    def patients(self, q='', limit='30', **kwargs):
        return _json(request.env['camp.api'].search_patients(q, limit=int(limit or 30)))

    # ── Write ──────────────────────────────────────────────────
    @camp_route('/api/camp/<int:camp_id>/tokens', ['POST'])
    def tokens(self, camp_id, **kwargs):
        if 'registration' not in request.env['camp.api']._roles():
            raise AccessError('Only registration staff can reserve token numbers.')
        count = int(_body().get('count') or 50)
        camp = request.env['camp.api']._get_camp(camp_id)
        return _json(camp.sudo()._reserve_tokens(count))

    @camp_route('/api/camp/<int:camp_id>/close', ['POST'])
    def close(self, camp_id, **kwargs):
        return _json(request.env['camp.api'].close_camp(camp_id))

    @camp_route('/api/camp/<int:camp_id>/sync', ['POST'])
    def sync(self, camp_id, **kwargs):
        return _json(request.env['camp.api'].sync(camp_id, _body()))
