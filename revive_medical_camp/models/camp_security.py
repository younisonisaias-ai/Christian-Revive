"""Security for Camp Mode: sign-in lockout with our own image CAPTCHA, an
audit log of who saw or changed patient records, remote sign-out of lost
phones, a first sign-in password change, and data retention."""
import base64
import hashlib
import io
import logging
import random
import re
import secrets
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

WINDOW_MINUTES = 15     # failures are counted over this window
CAPTCHA_AFTER = 3       # show a CAPTCHA after this many failures
LOCK_AFTER = 10         # lock the login after this many failures
LOCK_MINUTES = 15
CAPTCHA_MINUTES = 10    # a CAPTCHA must be answered within this time
AUDIT_KEEP_YEARS = 3

FONT_PATHS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
]


def password_problem(password, login=''):
    """Why a new camp password is too weak (None when it is fine)."""
    if len(password or '') < 8:
        return _('Use at least 8 characters.')
    if not re.search(r'[A-Za-z]', password) or not re.search(r'\d', password):
        return _('Use letters and numbers.')
    if login and password.lower() == login.lower():
        return _('The password cannot be the same as the login.')
    return None


class CampAuthThrottle(models.Model):
    """Failed camp sign-ins per login and per network address."""
    _name = 'camp.auth.throttle'
    _description = 'Camp sign-in attempts'

    key = fields.Char(required=True, index=True)
    failures = fields.Integer()
    window_start = fields.Datetime()
    locked_until = fields.Datetime()

    _key_unique = models.Constraint('UNIQUE(key)', 'One row per key.')

    @api.model
    def _rows(self, keys):
        rows = self.sudo().search([('key', 'in', keys)])
        now = fields.Datetime.now()
        stale = rows.filtered(lambda r: r.window_start and r.window_start < now - timedelta(minutes=WINDOW_MINUTES)
                              and not (r.locked_until and r.locked_until > now))
        stale.write({'failures': 0, 'window_start': False})
        return rows

    @api.model
    def status(self, keys):
        """(minutes locked, CAPTCHA needed) for these keys."""
        now = fields.Datetime.now()
        rows = self._rows(keys)
        locked = [r.locked_until for r in rows if r.locked_until and r.locked_until > now]
        minutes = max(((t - now).total_seconds() + 59) // 60 for t in locked) if locked else 0
        return int(minutes), any(r.failures >= CAPTCHA_AFTER for r in rows)

    @api.model
    def failed(self, keys, lock_key):
        now = fields.Datetime.now()
        rows = self._rows(keys)
        for key in keys:
            row = rows.filtered(lambda r: r.key == key)
            if not row:
                row = self.sudo().create({'key': key, 'failures': 0})
            vals = {'failures': row.failures + 1, 'window_start': row.window_start or now}
            # Only the login itself gets locked: a shared network (camp hotspot)
            # must not lock everybody out.
            if key == lock_key and vals['failures'] >= LOCK_AFTER:
                vals.update({'locked_until': now + timedelta(minutes=LOCK_MINUTES), 'failures': 0,
                             'window_start': False})
            row.write(vals)

    @api.model
    def succeeded(self, keys):
        self.sudo().search([('key', 'in', keys)]).unlink()

    @api.model
    def hit(self, key, limit, minutes=60):
        """Count one request; True when over [limit] in the window (e.g. bad referral codes)."""
        now = fields.Datetime.now()
        row = self.sudo().search([('key', '=', key)], limit=1)
        if row and row.window_start and row.window_start < now - timedelta(minutes=minutes):
            row.write({'failures': 0, 'window_start': now})
        if not row:
            row = self.sudo().create({'key': key, 'failures': 0, 'window_start': now})
        row.failures += 1
        return row.failures > limit


class CampCaptcha(models.Model):
    """Our own picture CAPTCHA: no outside service sees the users."""
    _name = 'camp.captcha'
    _description = 'Camp CAPTCHA'

    token = fields.Char(required=True, index=True)
    answer_hash = fields.Char(required=True)
    expires = fields.Datetime(required=True)

    @staticmethod
    def _hash(token, answer):
        return hashlib.sha256(f'{token}:{(answer or "").strip()}'.encode()).hexdigest()

    @api.model
    def new(self):
        """(token, PNG as base64) for a new 5-digit challenge."""
        self.sudo().search([('expires', '<', fields.Datetime.now())]).unlink()
        answer = ''.join(secrets.choice('23456789') for _i in range(5))   # no 0/1 (look like O/l)
        token = secrets.token_urlsafe(18)
        self.sudo().create({'token': token, 'answer_hash': self._hash(token, answer),
                            'expires': fields.Datetime.now() + timedelta(minutes=CAPTCHA_MINUTES)})
        return token, self._image(answer)

    @api.model
    def check(self, token, answer):
        """Single use: the challenge is gone after one try."""
        row = self.sudo().search([('token', '=', token or ''), ('expires', '>=', fields.Datetime.now())], limit=1)
        ok = bool(row) and secrets.compare_digest(row.answer_hash, self._hash(token, answer))
        row.unlink()
        return ok

    @staticmethod
    def _font(size):
        from PIL import ImageFont
        for path in FONT_PATHS:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        try:
            return ImageFont.load_default(size=size)
        except TypeError:   # old Pillow
            return ImageFont.load_default()

    @classmethod
    def _image(cls, text):
        from PIL import Image, ImageDraw
        rnd = random.SystemRandom()
        width, height = 220, 80
        img = Image.new('RGB', (width, height), (250, 247, 242))
        draw = ImageDraw.Draw(img)
        for _i in range(6):   # noise lines
            draw.line([(rnd.randint(0, width), rnd.randint(0, height)), (rnd.randint(0, width), rnd.randint(0, height))],
                      fill=(rnd.randint(120, 200), rnd.randint(120, 200), rnd.randint(120, 200)), width=2)
        x = 14
        for ch in text:
            glyph = Image.new('RGBA', (48, 64), (0, 0, 0, 0))
            ImageDraw.Draw(glyph).text((6, 4), ch, font=cls._font(46),
                                       fill=(rnd.randint(20, 90), rnd.randint(20, 70), rnd.randint(20, 90)))
            glyph = glyph.rotate(rnd.uniform(-28, 28), expand=False, resample=Image.BICUBIC)
            img.paste(glyph, (x, rnd.randint(4, 14)), glyph)
            x += 40
        for _i in range(160):   # noise dots
            draw.point((rnd.randint(0, width - 1), rnd.randint(0, height - 1)),
                       fill=(rnd.randint(60, 200), rnd.randint(60, 200), rnd.randint(60, 200)))
        out = io.BytesIO()
        img.save(out, format='PNG')
        return base64.b64encode(out.getvalue()).decode()


class CampRevokedKey(models.Model):
    """Keys of phones signed out from Odoo: the phone wipes its camp data
    when it next connects."""
    _name = 'camp.revoked.key'
    _description = 'Camp signed-out phone'

    index = fields.Char(required=True, index=True)
    user_id = fields.Many2one('res.users', ondelete='cascade')
    revoked_at = fields.Datetime(default=fields.Datetime.now)


AUDIT_ACTIONS = [
    ('view', 'Opened'),
    ('change', 'Changed'),
    ('export', 'Exported'),
    ('print', 'Printed'),
    ('download', 'Downloaded to a phone'),
    ('upload', 'Uploaded from a phone'),
    ('search', 'Searched'),
    ('sign_in', 'Signed in'),
    ('sign_in_failed', 'Failed sign-in'),
    ('delete', 'Personal data removed'),
    ('wipe', 'Phone signed out'),
]


class CampAuditLog(models.Model):
    _name = 'camp.audit.log'
    _description = 'Camp audit log'
    _order = 'id desc'
    _log_access = True

    date = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    user_id = fields.Many2one('res.users', default=lambda self: self.env.uid, index=True, ondelete='set null')
    action = fields.Selection(AUDIT_ACTIONS, required=True, index=True)
    model = fields.Char()
    res_id = fields.Integer()
    patient_id = fields.Many2one('camp.patient', ondelete='set null', index=True)
    camp_id = fields.Many2one('camp.camp', ondelete='set null', index=True)
    details = fields.Char()
    ip = fields.Char(string='Network address')

    @api.model
    def log(self, action, records=None, details='', camp=None, patients=None, user=None):
        """Write audit rows (never fails the action being logged)."""
        try:
            from odoo.http import request
            ip = request.httprequest.remote_addr if request else False
        except Exception:  # noqa: BLE001 - no request (cron, tests)
            ip = False
        try:
            vals = {'action': action, 'details': (details or '')[:250], 'ip': ip,
                    'user_id': (user or self.env.user).id, 'camp_id': camp.id if camp else False}
            if records is not None and len(records) and len(records) <= 50:
                rows = []
                for r in records:
                    patient = r if r._name == 'camp.patient' else r['patient_id'] if 'patient_id' in r._fields else False
                    camp_rec = r if r._name == 'camp.camp' else r['camp_id'] if 'camp_id' in r._fields else camp
                    rows.append({**vals, 'model': r._name, 'res_id': r.id, 'patient_id': patient.id if patient else False,
                                 'camp_id': camp_rec.id if camp_rec else vals['camp_id']})
                self.sudo().create(rows)
            elif patients:
                self.sudo().create([{**vals, 'model': 'camp.patient', 'res_id': p.id, 'patient_id': p.id}
                                    for p in patients[:500]])
            else:
                if records is not None:
                    vals.update({'model': records._name, 'details': f'{len(records)} records. {vals["details"]}'[:250]})
                self.sudo().create(vals)
        except Exception:  # noqa: BLE001
            _logger.exception('Camp audit log failed')

    @api.model
    def _cron_cleanup(self):
        self.sudo().search([('date', '<', fields.Datetime.now() - timedelta(days=365 * AUDIT_KEEP_YEARS))]).unlink()


# ── Audit hooks on patient records ─────────────────────────────
AUDITED_FIELDS_SKIP = {'write_date', 'write_uid', 'message_main_attachment_id', '__last_update'}


class CampAuditedMixin(models.AbstractModel):
    """Opening (one record in Odoo), changing and exporting are logged."""
    _name = 'camp.audited.mixin'
    _description = 'Camp audited records'

    def web_read(self, specification):
        res = super().web_read(specification)
        if len(self) == 1 and not self.env.su:
            self.env['camp.audit.log'].log('view', self)
        return res

    def write(self, vals):
        res = super().write(vals)
        changed = sorted(set(vals) - AUDITED_FIELDS_SKIP)
        if changed and not self.env.context.get('camp_no_audit'):
            self.env['camp.audit.log'].log('change', self, details=', '.join(changed)[:200])
        return res

    def export_data(self, fields_to_export):
        res = super().export_data(fields_to_export)   # Odoo checks the right to export first
        self.env['camp.audit.log'].log('export', self, details=', '.join(fields_to_export)[:200])
        return res


class CampPatientAudited(models.Model):
    _name = 'camp.patient'
    _inherit = ['camp.patient', 'camp.audited.mixin']

    anonymised = fields.Boolean(readonly=True, help='Personal details were removed (data retention or on request).')

    def action_anonymise(self):
        """Remove a patient's personal details, keeping anonymous counts
        (age, sex, diagnoses) for reports."""
        if not self.env.user.has_group('revive_medical_camp.group_camp_coordinator') and not self.env.su:
            raise UserError(_('Only a coordinator can remove patient data.'))
        for p in self.sudo():
            p.with_context(camp_no_audit=True).write({
                'name': _('Anonymised patient %s', p.patient_code or p.id), 'phone': False, 'guardian_name': False,
                'date_of_birth': False, 'allergies': False, 'consent_media': False, 'consent_messages': False,
                'anonymised': True,
            })
            p.visit_ids.with_context(camp_no_audit=True).write({'consent_signature': False})
            self.env['camp.visit.photo'].sudo().search([('visit_id', 'in', p.visit_ids.ids)]).unlink()
            self.env['camp.reminder'].sudo().search([('patient_id', '=', p.id)]).unlink()
            p.message_ids.sudo().unlink()
            self.env['camp.audit.log'].log('delete', p)
        return True

    @api.model
    def _cron_retention(self):
        years = int(self.env['ir.config_parameter'].sudo().get_param('revive_medical_camp.retention_years') or 0)
        if years <= 0:
            return
        limit = fields.Datetime.now() - timedelta(days=365 * years)
        old = self.sudo().search([('anonymised', '=', False), ('create_date', '<', limit)])
        old = old.filtered(lambda p: not p.visit_ids.filtered(lambda v: (v.arrived_at or v.create_date) >= limit))
        old.action_anonymise()


class CampVisitAudited(models.Model):
    _name = 'camp.visit'
    _inherit = ['camp.visit', 'camp.audited.mixin']


class CampConsultationAudited(models.Model):
    _name = 'camp.consultation'
    _inherit = ['camp.consultation', 'camp.audited.mixin']


class ResUsersCampSecurity(models.Model):
    _inherit = 'res.users'

    camp_must_change_password = fields.Boolean(
        string='Must change camp password',
        help='Set for new camp logins: Camp Mode asks for a new password at the first sign-in.')
    camp_signed_out_at = fields.Datetime(readonly=True)


class CampTeamMemberSecurity(models.Model):
    _inherit = 'camp.team.member'

    def action_sign_out_phone(self):
        """Lost or stolen phone: cancel its Camp Mode key; the phone wipes the
        camp data when it next connects."""
        from ..controllers.camp_api import API_SCOPE
        for m in self.filtered('user_id'):
            self.env.cr.execute('SELECT id, index FROM res_users_apikeys WHERE user_id = %s AND scope = %s',
                                (m.user_id.id, API_SCOPE))
            rows = self.env.cr.fetchall()
            for _key_id, index in rows:
                self.env['camp.revoked.key'].sudo().create({'index': index, 'user_id': m.user_id.id})
            self.env['res.users.apikeys'].sudo().browse([r[0] for r in rows])._remove()
            m.user_id.sudo().camp_signed_out_at = fields.Datetime.now()
            self.env['camp.audit.log'].log('wipe', m.camp_id, details=_('%(name)s: %(n)s phone(s) signed out',
                                                                        name=m.name, n=len(rows)), camp=m.camp_id)
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Phone signed out'),
            'message': _('The phone can no longer use Camp Mode and will delete this camp\'s data when it next connects.'),
            'type': 'success'}}


class CampSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    camp_retention_years = fields.Integer(
        string='Remove patient details after (years)', config_parameter='revive_medical_camp.retention_years',
        help='Patients not seen for this many years are anonymised every night (0 = keep).')


class IrActionsReportAudit(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        report = self._get_report(report_ref)
        if report.report_name.startswith('revive_medical_camp.') and res_ids:
            records = self.env[report.model].browse(res_ids)
            self.env['camp.audit.log'].log('print', records, details=report.name)
        return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
