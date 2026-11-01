"""Separate sign-ins for Bible College students, staff and admins.

Students have their own account on college.student: their number and a
password. They set the password with a one-time code from the college office,
which is also how a forgotten password is replaced. The token issued here goes
to the app and to the /college web pages, and is passed in as an argument.

Staff and admins sign in with the same email and PIN as every other staff
role, but only through the door that matches their role.
"""
import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

from .college_app_api import college_app_staff, normalize_code, token_student

CODE_DAYS = 7
MAX_FAILURES = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 8
MAX_PASSWORD = 128
CODE_LETTERS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
STAFF_DOORS = {
    'staff': ('college_staff',),
    'admin': ('college_admin', 'admin'),
}
WRONG_PASSWORD = 'Wrong student number or password'
WRONG_CODE = 'Wrong student number or sign-in code'
LOCKED = 'Too many wrong tries. Please wait %d minutes and try again.' % LOCK_MINUTES


class CollegeStudentAccount(models.Model):
    _inherit = 'college.student'

    has_password = fields.Boolean(string='Has a Password', readonly=True, copy=False)
    password_hash = fields.Char(copy=False, groups='base.group_system')
    signin_code_hash = fields.Char(copy=False, groups='base.group_system')
    signin_code_expires = fields.Datetime(copy=False, groups='base.group_system')
    failed_signins = fields.Integer(copy=False, groups='base.group_system')
    locked_until = fields.Datetime(copy=False, groups='base.group_system')

    # ── Sign-in codes (given out by the college office) ──────────

    def _new_signin_code(self):
        self.ensure_one()
        code = ''.join(secrets.choice(CODE_LETTERS) for _ in range(8))
        self.sudo().write({
            'signin_code_hash': self._crypt().hash(code),
            'signin_code_expires': fields.Datetime.now() + timedelta(days=CODE_DAYS),
            'failed_signins': 0,
            'locked_until': False,
        })
        return code

    def action_create_signin_code(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sign-in code',
            'res_model': 'college.signin.code',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_student_id': self.id,
                'default_code': self._new_signin_code(),
            },
        }

    @api.model
    def app_college_create_signin_code(self, student_id):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        student = self.sudo().browse(student_id)
        if not student.exists():
            return {'success': False, 'error': 'Student not found'}
        if student.state == 'withdrawn':
            return {'success': False, 'error': 'This student has withdrawn'}
        return {'success': True, 'signin_code': student._new_signin_code(), 'valid_days': CODE_DAYS}

    # ── Student sign-in ──────────────────────────────────────────

    @api.model
    def _crypt(self):
        return self.env['res.users']._crypt_context()

    @api.model
    def _account_by_code(self, code):
        code = normalize_code(code, 'BC-')
        if not code:
            return self.sudo().browse()
        student = self.sudo().search([('student_code', '=ilike', code)], limit=1)
        return student if student.state != 'withdrawn' else self.sudo().browse()

    def _is_locked(self):
        return bool(self.locked_until and self.locked_until > fields.Datetime.now())

    def _note_failure(self):
        failures = self.failed_signins + 1
        if failures >= MAX_FAILURES:
            self.write({'failed_signins': 0,
                        'locked_until': fields.Datetime.now() + timedelta(minutes=LOCK_MINUTES)})
        else:
            self.write({'failed_signins': failures})

    def _start_session(self, device_id=None):
        self.write({'failed_signins': 0, 'locked_until': False})
        token = self.env['college.student.session'].sudo()._issue(self, device_id)
        return {'success': True, 'session_token': token, 'code': self.student_code, 'name': self.name}

    @api.model
    def app_college_student_sign_in(self, code, password, device_id=None):
        student = self._account_by_code(code)
        password = str(password or '')[:MAX_PASSWORD]
        if not student or not student.password_hash or not password:
            return {'success': False, 'error': WRONG_PASSWORD}
        if student._is_locked():
            return {'success': False, 'error': LOCKED}
        if not self._crypt().verify(password, student.password_hash):
            student._note_failure()
            return {'success': False, 'error': WRONG_PASSWORD}
        return student._start_session(device_id)

    @api.model
    def app_college_student_activate(self, code, signin_code, password, device_id=None):
        """First sign-in or a forgotten password: the office's code sets a new password."""
        student = self._account_by_code(code)
        signin_code = str(signin_code or '').strip().upper().replace(' ', '').replace('-', '')
        password = str(password or '')
        if len(password) < MIN_PASSWORD:
            return {'success': False, 'error': 'Choose a password of at least %d characters' % MIN_PASSWORD}
        if len(password) > MAX_PASSWORD:
            return {'success': False, 'error': 'That password is too long'}
        if not student or not student.signin_code_hash or not signin_code:
            return {'success': False, 'error': WRONG_CODE}
        if student._is_locked():
            return {'success': False, 'error': LOCKED}
        if student.signin_code_expires < fields.Datetime.now():
            return {'success': False, 'error': 'This code has expired. Ask the college office for a new one.'}
        if not self._crypt().verify(signin_code, student.signin_code_hash):
            student._note_failure()
            return {'success': False, 'error': WRONG_CODE}
        student.write({
            'password_hash': self._crypt().hash(password),
            'has_password': True,
            'signin_code_hash': False,
            'signin_code_expires': False,
        })
        # A new password ends every earlier sign-in.
        self.env['college.student.session'].sudo().search([('student_id', '=', student.id)]).write({'revoked': True})
        return student._start_session(device_id)

    @api.model
    def app_college_student_sign_out(self, token):
        session = self.env['college.student.session'].sudo()._find(token)
        session.write({'revoked': True})
        return {'success': True}

    @api.model
    def app_college_my_studies(self, token):
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        return {'success': True, 'student': student._app_self_detail()}

    # ── Staff and admin sign-in ──────────────────────────────────

    @api.model
    def app_college_staff_sign_in(self, email, pin, door, device_id=None):
        allowed = STAFF_DOORS.get(door)
        if not allowed:
            return {'success': False, 'error': 'Invalid email or PIN'}
        Session = self.env['church.app.session']
        result = Session.app_staff_sign_in(email, pin, device_id=device_id)
        if not result.get('success'):
            return result
        role = result['staff'].get('staff_role')
        if role in allowed:
            return result
        Session._find(result['session_token'], 'staff').sudo().write({'revoked': True})
        if door == 'staff' and role in STAFF_DOORS['admin']:
            return {'success': False, 'error': 'This is an admin account. Please use College Admin sign-in.'}
        if door == 'admin' and role in STAFF_DOORS['staff']:
            return {'success': False, 'error': 'This is a staff account. Please use College Staff sign-in.'}
        return {'success': False, 'error': 'This account does not have Bible College access.'}


class CollegeStudentSession(models.Model):
    _name = 'college.student.session'
    _description = 'Bible College Student Sign-in'
    _order = 'id desc'
    _rec_name = 'student_id'

    SESSION_DAYS = 90

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    token_hash = fields.Char(required=True, index=True)
    device_id = fields.Char()
    expires_at = fields.Datetime(required=True)
    last_used_at = fields.Datetime()
    revoked = fields.Boolean(default=False, index=True)

    _token_hash_uniq = models.Constraint('unique(token_hash)', 'Duplicate session token.')

    @staticmethod
    def _hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @api.model
    def _issue(self, student, device_id=None):
        token = secrets.token_urlsafe(32)
        self.sudo().create({
            'student_id': student.id,
            'token_hash': self._hash(token),
            'device_id': (device_id or '')[:128] or False,
            'expires_at': fields.Datetime.now() + timedelta(days=self.SESSION_DAYS),
        })
        return token

    @api.model
    def _find(self, token):
        if not token or not isinstance(token, str):
            return self.sudo().browse()
        session = self.sudo().search([('token_hash', '=', self._hash(token)), ('revoked', '=', False)], limit=1)
        now = fields.Datetime.now()
        if not session or session.expires_at < now or session.student_id.state == 'withdrawn':
            return self.sudo().browse()
        if not session.last_used_at or now - session.last_used_at > timedelta(hours=1):
            session.write({'last_used_at': now, 'expires_at': now + timedelta(days=self.SESSION_DAYS)})
        return session

    @api.model
    def _cron_purge(self):
        self.sudo().search(['|', ('revoked', '=', True), ('expires_at', '<', fields.Datetime.now())]).unlink()


class CollegeSigninCode(models.TransientModel):
    """Shows a new sign-in code to the staff member, once."""
    _name = 'college.signin.code'
    _description = 'Bible College Sign-in Code'

    student_id = fields.Many2one('college.student', readonly=True)
    code = fields.Char(string='Sign-in Code', readonly=True)
