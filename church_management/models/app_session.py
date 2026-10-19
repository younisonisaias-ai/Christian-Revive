"""Per-person app sessions.

The app talks to the server through one shared account, and every request
names the member (requester_partner_id) or staff member (requester_staff_id)
it acts for. On its own the server cannot tell whether that is true. A
session token, issued at sign-in and sent with every request, proves it:

  X-Revive-Session        the signed-in member's token
  X-Revive-Staff-Session  the signed-in staff member's token

Only a SHA-256 hash of each token is stored. `_church_caller_scope` (used by
the church screens) refuses a request whose named member or staff member does
not match the token. Requests without a token keep working until the system
parameter church_management.require_app_session is set to True, so older app
versions are not cut off before the update reaches everyone. Attendance always
requires a token.
"""
import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

SESSION_DAYS = 90
TOUCH_EVERY = timedelta(hours=1)
MEMBER_HEADER = 'X-Revive-Session'
STAFF_HEADER = 'X-Revive-Staff-Session'


def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


class ChurchAppSession(models.Model):
    _name = 'church.app.session'
    _description = 'App Sign-in Session'
    _order = 'last_used_at desc, id desc'

    kind = fields.Selection([('member', 'Member'), ('staff', 'Staff')], required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Member', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Staff', ondelete='cascade', index=True)
    token_hash = fields.Char(required=True, index=True, copy=False)
    device_id = fields.Char(string='Device')
    last_used_at = fields.Datetime(string='Last used', default=fields.Datetime.now)
    expires_at = fields.Datetime(string='Expires', required=True)
    revoked = fields.Boolean(default=False, index=True)

    _token_hash_uniq = models.Constraint('unique(token_hash)', 'Duplicate session token.')

    # ── Issuing and reading ─────────────────────────────────────

    @api.model
    def _issue(self, kind, partner=None, employee=None, device_id=None):
        """Create a session and return the raw token (shown only once)."""
        token = secrets.token_urlsafe(32)
        self.sudo().create({
            'kind': kind,
            'partner_id': partner.id if partner else False,
            'employee_id': employee.id if employee else False,
            'token_hash': _hash(token),
            'device_id': (device_id or '')[:128] or False,
            'expires_at': fields.Datetime.now() + timedelta(days=SESSION_DAYS),
        })
        return token

    @api.model
    def _token_from_request(self, header):
        """Token sent with this request. Tests pass it through the context."""
        ctx_key = 'app_staff_session_token' if header == STAFF_HEADER else 'app_session_token'
        if self.env.context.get(ctx_key):
            return self.env.context[ctx_key]
        try:
            from odoo.http import request
            if request and getattr(request, 'httprequest', None) is not None:
                return request.httprequest.headers.get(header)
        except RuntimeError:  # no request (cron, shell)
            return None
        return None

    @api.model
    def _find(self, token, kind):
        if not token:
            return self.browse()
        session = self.sudo().search([
            ('token_hash', '=', _hash(token)), ('kind', '=', kind), ('revoked', '=', False),
        ], limit=1)
        now = fields.Datetime.now()
        if not session or session.expires_at < now:
            return self.browse()
        if kind == 'staff' and not (session.employee_id.active and session.employee_id.is_app_active):
            return self.browse()
        if not session.last_used_at or now - session.last_used_at > TOUCH_EVERY:
            # Sliding expiry; written at most hourly to keep requests cheap.
            session.write({'last_used_at': now,
                           'expires_at': now + timedelta(days=SESSION_DAYS)})
        return session

    @api.model
    def _current_member(self):
        return self._find(self._token_from_request(MEMBER_HEADER), 'member')

    @api.model
    def _current_staff(self):
        return self._find(self._token_from_request(STAFF_HEADER), 'staff')

    @api.model
    def _required(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'church_management.require_app_session', 'False').lower() in ('1', 'true', 'yes')

    @api.model
    def _verify_requester(self, requester_partner_id=None, requester_staff_id=None):
        """True when the named member/staff matches this request's tokens.

        Without tokens this is True only while sessions are not yet required.
        Other modules call this before trusting requester ids.
        """
        member = self._current_member()
        staff = self._current_staff()
        if requester_staff_id:
            if staff:
                return staff.employee_id.id == int(requester_staff_id)
            return not self._required()
        if requester_partner_id:
            if member:
                return member.partner_id.id == int(requester_partner_id)
            return not self._required()
        return True

    # ── Sign-in endpoints ───────────────────────────────────────

    @api.model
    def app_member_sign_in(self, email, password, device_id=None):
        """Member sign-in that also returns a session token."""
        result = self.env['res.partner'].app_login(email, password)
        if not result.get('success'):
            return result
        partner = self.env['res.partner'].sudo().browse(result['partner_id'])
        return dict(result, session_token=self._issue('member', partner=partner, device_id=device_id))

    @api.model
    def app_member_register(self, email, password, vals, device_id=None):
        """Registration that signs the new member in with a session token."""
        result = self.env['res.partner'].app_register(email, password, vals)
        if not result.get('success'):
            return result
        partner = self.env['res.partner'].sudo().browse(result['partner_id'])
        return dict(result, session_token=self._issue('member', partner=partner, device_id=device_id))

    @api.model
    def app_staff_sign_in(self, email, pin, device_id=None):
        """Staff sign-in with email + PIN, checked here on the server."""
        email = (email or '').strip().lower()
        pin = (pin or '').strip()
        if not email or not pin:
            return {'success': False, 'error': 'Invalid email or PIN'}
        employee = self.env['hr.employee'].sudo().search([
            ('app_email', '=', email), ('is_app_active', '=', True),
        ], limit=1)
        if not employee or not employee.app_pin or not secrets.compare_digest(employee.app_pin, pin):
            return {'success': False, 'error': 'Invalid email or PIN'}
        staff = employee.read(['id', 'name', 'staff_role', 'app_email', 'job_title',
                               'work_phone', 'assigned_project_ids'])[0]
        return {'success': True, 'staff': staff,
                'session_token': self._issue('staff', employee=employee, device_id=device_id)}

    @api.model
    def app_admin_session(self, device_id=None):
        """Staff token for a church admin who signed in with their own ERP login.

        Called in that admin's own authenticated session (not the shared app
        account), so env.user is the person who typed the password.
        """
        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid), ('staff_role', '=', 'admin'),
            ('is_app_active', '=', True),
        ])
        if len(employee) != 1:
            return {'success': False, 'error': 'No church Admin record is linked to this account.'}
        return {'success': True, 'staff_id': employee.id,
                'session_token': self._issue('staff', employee=employee, device_id=device_id)}

    @api.model
    def app_sign_out(self):
        """Revoke the tokens sent with this request."""
        sessions = self._current_member() | self._current_staff()
        sessions.sudo().write({'revoked': True})
        return {'success': True}

    @api.model
    def _cron_purge(self):
        self.sudo().search(['|', ('revoked', '=', True),
                            ('expires_at', '<', fields.Datetime.now())]).unlink()


class ResPartnerSessionCheck(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _church_caller_scope(self, requester_partner_id=None, requester_staff_id=None):
        """Refuse callers whose named member/staff does not match their token."""
        if not self.env['church.app.session']._verify_requester(
                requester_partner_id=requester_partner_id if not requester_staff_id else None,
                requester_staff_id=requester_staff_id):
            return ('denied', None)
        return super()._church_caller_scope(requester_partner_id, requester_staff_id)
