"""Smart Attendance: church locations, per-event check-in settings, and one
check-in path used by every source (at the church, family, QR, kiosk, staff).

Rules that need no database live in attendance_rules.py. Members are
identified by their session token (app_session.py), never by an id the app
sends. No raw coordinates are stored: only whether the location was verified,
the distance and the reading's accuracy.
"""
import logging
from datetime import timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from . import attendance_rules as rules

_logger = logging.getLogger(__name__)

RADIUS_PRESETS = [50, 75, 100, 150, 200]
STAFF_ROLES = ('admin', 'pastor', 'church_volunteer')

# Messages members can read; never raw GPS or technical errors.
REASONS = {
    'not_found': 'This event is not available.',
    'not_open': 'Check-in for this event is not open right now.',
    'upcoming': 'Check-in has not opened yet.',
    'closed': 'Check-in for this event has closed.',
    'cancelled': 'This event was cancelled.',
    'not_enabled': 'Attendance is not taken for this event.',
    'family_off': 'Family check-in is not available for this event.',
    'guests_off': 'Guests are not checked in for this event.',
    'age': 'This event is for a different age group.',
    'not_authorized': 'You can check in yourself and your dependents only.',
    'not_family': 'This person is not in your family.',
    'not_verified': 'This family member is waiting for church verification.',
    'adult': 'Adults check themselves in.',
    'location_missing': 'Turn on location to check in at the church.',
    'location_outside': "You don't seem to be at the church yet.",
    'location_low_accuracy': "Your location couldn't be verified accurately. "
                             "Move closer to the church or try again.",
    'offline_too_old': 'This saved check-in is too old to send.',
    'offline_future_time': "Your phone's clock looks wrong. Check the date and time.",
    'offline_missing_time': 'This saved check-in is missing its time.',
    'manual_off': 'Check-in without location is not allowed for this event.',
    'already': 'Already checked in.',
    'not_a_person': 'This person was not found.',
}


def _now():
    return fields.Datetime.now()


class ChurchLocation(models.Model):
    _name = 'church.location'
    _description = 'Church Location'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    address = fields.Char()
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    geofence_radius_m = fields.Integer(
        string='Check-in radius (m)', default=rules.DEFAULT_RADIUS_M,
        help='How close to the church a member must be. Phones are not exact; '
             '100 m suits most buildings.')
    radius_preset = fields.Selection(
        [(str(r), f'{r} m') for r in RADIUS_PRESETS] + [('custom', 'Custom')],
        string='Radius', compute='_compute_radius_preset', inverse='_inverse_radius_preset')
    geofence_enabled = fields.Boolean(
        string='Arrival reminders', default=True,
        help='The app offers check-in when a member opens it at the church.')
    location_validation_enabled = fields.Boolean(
        string='Verify location at check-in', default=True,
        help='The server checks the phone is at the church before recording attendance.')
    timezone = fields.Selection(
        lambda self: [(tz, tz) for tz in pytz.common_timezones], string='Time zone',
        default=lambda self: self.env['church.service.schedule']._church_tz().zone)
    active = fields.Boolean(default=True)

    @api.depends('geofence_radius_m')
    def _compute_radius_preset(self):
        for rec in self:
            rec.radius_preset = str(rec.geofence_radius_m) \
                if rec.geofence_radius_m in RADIUS_PRESETS else 'custom'

    def _inverse_radius_preset(self):
        for rec in self:
            if rec.radius_preset and rec.radius_preset != 'custom':
                rec.geofence_radius_m = int(rec.radius_preset)

    @api.constrains('latitude', 'longitude', 'geofence_radius_m')
    def _check_values(self):
        for rec in self:
            if rec.geofence_radius_m < 10 or rec.geofence_radius_m > 5000:
                raise ValidationError('The check-in radius must be between 10 and 5,000 metres.')
            if (rec.latitude or rec.longitude) and not rules.valid_coordinates(rec.latitude, rec.longitude):
                raise ValidationError('Enter a valid latitude and longitude for the church.')

    def _has_coordinates(self):
        self.ensure_one()
        return rules.valid_coordinates(self.latitude, self.longitude)

    def _tz(self):
        self.ensure_one()
        try:
            return pytz.timezone(self.timezone) if self.timezone \
                else self.env['church.service.schedule']._church_tz()
        except pytz.UnknownTimeZoneError:
            return self.env['church.service.schedule']._church_tz()


ATTENDANCE_SETTINGS = [
    'location_id', 'attendance_enabled', 'smart_checkin_enabled', 'geofence_required',
    'family_checkin_enabled', 'guest_checkin_enabled', 'manual_checkin_enabled',
    'checkin_open_minutes_before', 'checkin_close_minutes_after_start',
    'grace_minutes', 'radius_override_m', 'notify_on_arrival', 'min_age', 'max_age',
]


class AttendanceSettingsMixin(models.AbstractModel):
    """Attendance settings shared by events and the weekly schedules that create them."""
    _name = 'church.attendance.settings.mixin'
    _description = 'Attendance settings'

    location_id = fields.Many2one('church.location', string='Church location')
    attendance_enabled = fields.Boolean(string='Take attendance', default=True)
    smart_checkin_enabled = fields.Boolean(
        string='Members check in from the app', default=True)
    geofence_required = fields.Boolean(
        string='Must be at the church', default=True,
        help='Members can check in from the app only when their phone is at the church.')
    family_checkin_enabled = fields.Boolean(string='Family check-in', default=True)
    guest_checkin_enabled = fields.Boolean(string='Guests', default=True)
    manual_checkin_enabled = fields.Boolean(
        string='Staff check-in', default=True,
        help='Staff can check people in by hand, for example when a phone has no location.')
    checkin_open_minutes_before = fields.Integer(
        string='Opens (minutes before start)', default=rules.DEFAULT_OPEN_MINUTES_BEFORE)
    checkin_close_minutes_after_start = fields.Integer(
        string='Closes (minutes after start)', default=rules.DEFAULT_CLOSE_MINUTES_AFTER_START)
    grace_minutes = fields.Integer(
        string='Late after (minutes)', default=rules.DEFAULT_GRACE_MINUTES,
        help='Check-ins later than this after the start are marked late.')
    radius_override_m = fields.Integer(
        string='Radius for this event (m)',
        help="Leave empty to use the location's radius.")
    notify_on_arrival = fields.Boolean(string='Remind members to check in', default=True)
    min_age = fields.Integer(string='Minimum age', help='Leave 0 for everyone.')
    max_age = fields.Integer(string='Maximum age', help='Leave 0 for everyone.')


class ChurchServiceAttendance(models.Model):
    _name = 'church.service'
    _inherit = ['church.service', 'church.attendance.settings.mixin']

    checkin_close_at = fields.Datetime(
        string='Check-in closes at', help='Overrides "Closes (minutes after start)".')
    cancelled = fields.Boolean(
        string='Cancelled', index=True,
        help='A cancelled service stays on the calendar but takes no check-ins.')

    @api.model_create_multi
    def create(self, vals_list):
        # Services made by a weekly schedule inherit its attendance settings.
        Schedule = self.env['church.service.schedule'].sudo()
        for vals in vals_list:
            if vals.get('schedule_id'):
                schedule = Schedule.browse(vals['schedule_id'])
                for name in ATTENDANCE_SETTINGS:
                    if name not in vals:
                        value = schedule[name]
                        vals[name] = value.id if isinstance(value, models.BaseModel) else value
        return super().create(vals_list)

    # ── Check-in window and eligibility ─────────────────────────

    def _checkin_window(self):
        self.ensure_one()
        return rules.check_in_window(
            self.date_start, self.date_end, self.checkin_open_minutes_before,
            self.checkin_close_minutes_after_start, self.checkin_close_at)

    def _radius_m(self):
        self.ensure_one()
        return self.radius_override_m or self.location_id.geofence_radius_m or rules.DEFAULT_RADIUS_M

    def _availability(self, at=None):
        """'open', 'upcoming', 'closed', 'cancelled' or 'not_enabled'."""
        self.ensure_one()
        if self.cancelled:
            return 'cancelled'
        if not (self.attendance_enabled and self.is_active and self.date_start):
            return 'not_enabled'
        opens, closes = self._checkin_window()
        return rules.window_state(at or _now(), opens, closes)

    def _age_problem(self, partner):
        self.ensure_one()
        if not (self.min_age or self.max_age) or not partner.date_of_birth:
            return None
        today = fields.Date.context_today(self)
        dob = partner.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if (self.min_age and age < self.min_age) or (self.max_age and age > self.max_age):
            return 'age'
        return None

    def _location_result(self, latitude, longitude, accuracy):
        """(result, distance) for a reading against this service's church."""
        self.ensure_one()
        location = self.location_id
        if not (self.geofence_required and location and location.location_validation_enabled
                and location._has_coordinates()):
            return 'not_required', None
        return rules.check_location(location.latitude, location.longitude, self._radius_m(),
                                    latitude, longitude, accuracy)

    def _local_labels(self):
        self.ensure_one()
        tz = self.location_id._tz() if self.location_id else \
            self.env['church.service.schedule']._church_tz()

        def local(dt):
            return pytz.UTC.localize(dt).astimezone(tz) if dt else None
        start, end = local(self.date_start), local(self.date_end)
        fmt = '%I:%M %p'
        time_label = start.strftime(fmt).lstrip('0') if start else ''
        if end:
            time_label += ' – ' + end.strftime(fmt).lstrip('0')
        return {'time_label': time_label,
                'date_label': start.strftime('%A, %d %B') if start else '',
                'timezone': tz.zone}


class ChurchServiceScheduleAttendance(models.Model):
    _name = 'church.service.schedule'
    _inherit = ['church.service.schedule', 'church.attendance.settings.mixin']


class ChurchAttendanceLog(models.Model):
    """Who did what to attendance. Never stores coordinates."""
    _name = 'church.attendance.log'
    _description = 'Attendance History'
    _order = 'create_date desc, id desc'

    action = fields.Selection([
        ('created', 'Checked in'), ('family_created', 'Family checked in'),
        ('manual_created', 'Checked in by staff'), ('edited', 'Edited'),
        ('removed', 'Removed'), ('restored', 'Restored'),
        ('location_failed', 'Location not verified'),
    ], required=True, index=True)
    attendance_id = fields.Many2one('church.event.attendance', ondelete='set null', index=True)
    service_id = fields.Many2one('church.service', ondelete='cascade', index=True)
    member_id = fields.Many2one('res.partner', string='Person', ondelete='set null')
    actor_partner_id = fields.Many2one('res.partner', string='By member', ondelete='set null')
    actor_staff_id = fields.Many2one('hr.employee', string='By staff', ondelete='set null')
    method = fields.Char()
    details = fields.Char(help='Reason, status change or distance; never a location.')

    def write(self, vals):
        raise ValidationError('Attendance history cannot be changed.')

    def unlink(self):
        raise ValidationError('Attendance history cannot be deleted.')


class ChurchEventAttendanceSmart(models.Model):
    _inherit = 'church.event.attendance'

    method = fields.Selection(selection_add=[
        ('geofence_self', 'At church (self)'),
        ('geofence_family', 'At church (family)'),
        ('member_manual', 'Member, no location'),
        ('staff_manual', 'Staff'),
        ('admin_manual', 'Admin'),
    ], ondelete={'geofence_self': 'set default', 'geofence_family': 'set default',
                 'member_manual': 'set default', 'staff_manual': 'set default',
                 'admin_manual': 'set default'})
    status = fields.Selection([
        ('present', 'Present'), ('late', 'Late'), ('excused', 'Excused'),
        ('cancelled', 'Cancelled'), ('removed', 'Removed'),
    ], default='present', required=True, index=True)
    is_late = fields.Boolean(string='Late', index=True)
    attendee_kind = fields.Selection([
        ('member', 'Member'), ('child', 'Child'), ('guest', 'Guest'),
    ], string='Attendee', index=True, default='member')
    location_id = fields.Many2one('church.location', index=True)
    family_id = fields.Many2one('church.family', string='Family', index=True)
    checked_in_by_partner_id = fields.Many2one('res.partner', string='Checked in by member')
    verification = fields.Selection([
        ('live', 'Location checked'), ('offline', 'Location checked offline'),
        ('not_required', 'No location needed'), ('staff', 'Staff'),
    ], string='Verification')
    location_verified = fields.Boolean(string='Location verified')
    distance_m = fields.Float(string='Distance (m)', digits=(10, 1))
    accuracy_m = fields.Float(string='Accuracy (m)', digits=(10, 1))
    device_id = fields.Char(string='Device')
    idempotency_key = fields.Char(index=True, copy=False)
    notes = fields.Text()

    _idempotency_key_uniq = models.Constraint(
        'unique(idempotency_key)', 'This check-in was already received.')

    # ── People and permissions ──────────────────────────────────

    @api.model
    def _person_facts(self, partner):
        return {
            'id': partner.id,
            'family_id': partner.family_id.id or False,
            'is_family_head': bool(partner.is_family_head),
            'relationship': partner.family_relationship or False,
            'verified': partner.family_verified is not False,
            'guardian_id': partner.guardian_id.id or False,
            'date_of_birth': partner.date_of_birth,
        }

    @api.model
    def _member_may_check_in(self, acting, attendee):
        """(allowed, reason) for a member checking someone in."""
        return rules.family_permission(self._person_facts(acting), self._person_facts(attendee),
                                       fields.Date.context_today(self))

    @api.model
    def _household(self, partner):
        """People a member can see on the check-in screen: themselves, their
        family, and anyone they are guardian of."""
        Partner = self.env['res.partner'].sudo()
        people = partner
        if partner.family_id:
            people |= Partner.search([('family_id', '=', partner.family_id.id)])
        people |= Partner.search([('guardian_id', '=', partner.id)])
        return people

    @api.model
    def _attendee_kind(self, partner):
        minor = rules.is_minor(partner.date_of_birth, fields.Date.context_today(self))
        if minor or (minor is None and partner.family_relationship in rules.CHILD_RELATIONSHIPS):
            return 'child'
        if not partner.is_member and partner.visitor_stage:
            return 'guest'
        return 'member'

    @api.model
    def _staff_from_session(self):
        session = self.env['church.app.session']._current_staff()
        if session and session.employee_id.staff_role in STAFF_ROLES:
            return session.employee_id
        return self.env['hr.employee']

    @api.model
    def _member_from_session(self):
        session = self.env['church.app.session']._current_member()
        return session.partner_id if session else self.env['res.partner']

    @api.model
    def _log(self, action, service=None, member=None, attendance=None, actor_partner=None,
             actor_staff=None, method=None, details=None):
        self.env['church.attendance.log'].sudo().create({
            'action': action,
            'service_id': service.id if service else (attendance.event_id.id if attendance else False),
            'member_id': member.id if member else (attendance.member_id.id if attendance else False),
            'attendance_id': attendance.id if attendance else False,
            'actor_partner_id': actor_partner.id if actor_partner else False,
            'actor_staff_id': actor_staff.id if actor_staff else False,
            'method': method or False,
            'details': (details or '')[:250] or False,
        })

    # ── The one check-in path ───────────────────────────────────

    @api.model
    def _check_in(self, items, method, acting_partner=None, acting_staff=None,
                  latitude=None, longitude=None, accuracy=None, captured_at=None,
                  offline=False, device_id=None, idempotency_key=None, notes=None):
        """Check people in. Used by every source.

        items: [{'member_id': int, 'service_id': int}]. Exactly one of
        acting_partner / acting_staff is set. Returns
        {'successful': [...], 'already': [...], 'failed': [...]}; each entry
        has member_id, member_name, service_id and, on failure, reason/message.
        Everything is validated with server time (or, for an accepted offline
        attempt, the time it was captured) before any record is written.
        """
        Service = self.env['church.service'].sudo()
        Partner = self.env['res.partner'].sudo()
        server_now = _now()
        at = server_now
        result = {'successful': [], 'already': [], 'failed': []}

        def fail(member, service_id, reason):
            result['failed'].append({
                'member_id': member.id if member else None,
                'member_name': member.name if member else '',
                'service_id': service_id, 'reason': reason,
                'message': REASONS.get(reason, REASONS['not_open'])})

        if offline:
            problem = rules.offline_capture_problem(captured_at, server_now)
            if problem:
                for item in items:
                    fail(Partner.browse(item.get('member_id')).exists(), item.get('service_id'),
                         'offline_' + problem)
                return result
            at = captured_at

        location_cache = {}
        logged_location_failures = set()
        seen = set()
        for item in items:
            member = Partner.browse(int(item.get('member_id') or 0)).exists()
            service = Service.browse(int(item.get('service_id') or 0)).exists()
            if not member:
                fail(None, item.get('service_id'), 'not_a_person')
                continue
            if not service:
                fail(member, item.get('service_id'), 'not_found')
                continue
            if (member.id, service.id) in seen:
                continue
            seen.add((member.id, service.id))

            # Who may check this person in.
            if acting_partner:
                allowed, why = self._member_may_check_in(acting_partner, member)
                if not allowed:
                    fail(member, service.id, why if why in REASONS else 'not_authorized')
                    continue
                if member != acting_partner and not service.family_checkin_enabled:
                    fail(member, service.id, 'family_off')
                    continue
            elif not (acting_staff and service.manual_checkin_enabled):
                fail(member, service.id, 'not_authorized')
                continue

            # The event itself. Staff may record attendance outside the
            # check-in window (late corrections); members may not.
            state = service._availability(at)
            blocked = state in ('cancelled', 'not_enabled') if acting_staff else state != 'open'
            if blocked:
                fail(member, service.id, state if state in REASONS else 'not_open')
                continue
            age = service._age_problem(member)
            if age:
                fail(member, service.id, age)
                continue
            kind = self._attendee_kind(member)
            if kind == 'guest' and not service.guest_checkin_enabled:
                fail(member, service.id, 'guests_off')
                continue

            # Location, checked once per service per request.
            loc_result, distance = 'not_required', None
            if acting_partner:
                if service.id not in location_cache:
                    location_cache[service.id] = service._location_result(latitude, longitude, accuracy)
                loc_result, distance = location_cache[service.id]
                if loc_result == 'not_required' and method in ('geofence_self', 'geofence_family') \
                        and not service.smart_checkin_enabled:
                    fail(member, service.id, 'not_enabled')
                    continue
                if loc_result not in ('ok', 'not_required'):
                    reason = 'location_' + loc_result
                    if service.id not in logged_location_failures:
                        logged_location_failures.add(service.id)
                        self._log('location_failed', service=service, actor_partner=acting_partner,
                                  method=method, details=f'{loc_result}'
                                  + (f', {round(distance)} m' if distance is not None else ''))
                    _logger.info('attendance_location_verification_failed service=%s result=%s',
                                 service.id, loc_result)
                    fail(member, service.id, reason)
                    continue

            # Already checked in (a removed record is brought back instead).
            item_key = f'{idempotency_key}:{member.id}:{service.id}' if idempotency_key else False
            existing = self.sudo().search([('event_id', '=', service.id), ('member_id', '=', member.id)],
                                          limit=1)
            if existing and existing.status not in ('removed', 'cancelled'):
                result['already'].append({
                    'member_id': member.id, 'member_name': member.name, 'service_id': service.id,
                    'attendance_id': existing.id,
                    'check_in_time': fields.Datetime.to_string(existing.check_in_time),
                    'message': REASONS['already']})
                continue

            late = rules.is_late(at, service.date_start, service.grace_minutes)
            vals = {
                'event_id': service.id, 'member_id': member.id, 'check_in_time': at,
                'method': method, 'status': 'late' if late else 'present', 'is_late': late,
                'attendee_kind': kind, 'location_id': service.location_id.id or False,
                'family_id': member.family_id.id or False,
                'checked_in_by_partner_id': acting_partner.id if acting_partner else False,
                'checked_in_by_staff_id': acting_staff.id if acting_staff else False,
                'verification': ('staff' if acting_staff else 'not_required' if loc_result == 'not_required'
                                 else 'offline' if offline else 'live'),
                'location_verified': loc_result == 'ok',
                'distance_m': round(distance, 1) if distance is not None else False,
                'accuracy_m': float(accuracy) if (accuracy is not None and loc_result == 'ok') else False,
                'device_id': (device_id or '')[:128] or False,
                'idempotency_key': item_key,
                'notes': notes or False,
            }
            try:
                with self.env.cr.savepoint():
                    if existing:
                        existing.write(vals)
                        record, action = existing, 'restored'
                    else:
                        record = self.sudo().create(vals)
                        action = 'manual_created' if acting_staff else \
                            'family_created' if member != acting_partner else 'created'
            except Exception:  # unique race: another device just checked them in
                again = self.sudo().search([('event_id', '=', service.id), ('member_id', '=', member.id)],
                                           limit=1)
                if again:
                    result['already'].append({
                        'member_id': member.id, 'member_name': member.name, 'service_id': service.id,
                        'attendance_id': again.id,
                        'check_in_time': fields.Datetime.to_string(again.check_in_time),
                        'message': REASONS['already']})
                else:
                    fail(member, service.id, 'not_open')
                continue
            self._log(action, attendance=record, actor_partner=acting_partner, actor_staff=acting_staff,
                      method=method, details='late' if late else None)
            if member.visitor_stage in ('new', 'contacted') and self.sudo().search_count(
                    [('member_id', '=', member.id), ('status', 'not in', ('removed', 'cancelled'))]) >= 2:
                member.write({'visitor_stage': 'returning'})
            result['successful'].append({
                'member_id': member.id, 'member_name': member.name, 'service_id': service.id,
                'attendance_id': record.id, 'is_late': late,
                'check_in_time': fields.Datetime.to_string(record.check_in_time)})

        _logger.info('attendance_checkin method=%s ok=%d already=%d failed=%d',
                     method, len(result['successful']), len(result['already']), len(result['failed']))
        return result

    @api.model
    def _replay(self, idempotency_key, items):
        """A repeated request (double tap, retry) returns the first result."""
        if not idempotency_key:
            return None
        records = self.sudo().search([('idempotency_key', '=like', f'{idempotency_key}:%')])
        if not records:
            return None
        done = {(r.member_id.id, r.event_id.id): r for r in records}
        result = {'successful': [], 'already': [], 'failed': [], 'replayed': True}
        for item in items:
            rec = done.get((int(item.get('member_id') or 0), int(item.get('service_id') or 0)))
            if rec:
                result['successful'].append({
                    'member_id': rec.member_id.id, 'member_name': rec.member_id.name,
                    'service_id': rec.event_id.id, 'attendance_id': rec.id, 'is_late': rec.is_late,
                    'check_in_time': fields.Datetime.to_string(rec.check_in_time)})
        return result if result['successful'] else None

    # ── Member endpoints (session token required) ──────────────

    @api.model
    def _service_payload(self, service, people, at):
        opens, closes = service._checkin_window()
        records = self.sudo().search([('event_id', '=', service.id), ('member_id', 'in', people.ids),
                                      ('status', 'not in', ('removed', 'cancelled'))])
        payload = {
            'service_id': service.id, 'name': service.name,
            'service_type': service.service_type,
            'date_start': fields.Datetime.to_string(service.date_start),
            'date_end': fields.Datetime.to_string(service.date_end) if service.date_end else False,
            'opens_at': fields.Datetime.to_string(opens),
            'closes_at': fields.Datetime.to_string(closes),
            'state': service._availability(at),
            'location_id': service.location_id.id or False,
            'location_name': service.location_id.name or service.location or '',
            'family_checkin': service.family_checkin_enabled,
            'location_required': service._location_result(None, None, None)[0] != 'not_required',
            'remind': service.notify_on_arrival and service.smart_checkin_enabled,
            'checked_in': [{'member_id': r.member_id.id, 'member_name': r.member_id.name,
                            'check_in_time': fields.Datetime.to_string(r.check_in_time),
                            'is_late': r.is_late} for r in records],
        }
        payload.update(service._local_labels())
        return payload

    @api.model
    def app_attendance_home(self, latitude=None, longitude=None, accuracy=None):
        """Everything the member's Attendance card needs, for the signed-in member.

        The location reading is used only to say "you are at the church"; it
        is not stored.
        """
        partner = self._member_from_session()
        if not partner:
            return {'success': False, 'error': 'sign_in_required'}
        at = _now()
        people = self._household(partner)
        services = self.env['church.service'].sudo().search([
            ('attendance_enabled', '=', True), ('is_active', '=', True), ('cancelled', '=', False),
            ('smart_checkin_enabled', '=', True),
            ('date_start', '>=', at - timedelta(hours=12)), ('date_start', '<=', at + timedelta(days=7)),
        ], order='date_start asc, id asc')
        open_now, upcoming = [], []
        for service in services:
            state = service._availability(at)
            if state == 'open':
                open_now.append(self._service_payload(service, people, at))
            elif state == 'upcoming':
                upcoming.append(self._service_payload(service, people, at))

        household = []
        for person in people.sorted(lambda p: (p != partner, p.name or '')):
            allowed, why = self._member_may_check_in(partner, person)
            household.append({
                'member_id': person.id, 'name': person.name, 'is_self': person == partner,
                'relationship': person.family_relationship or False,
                'kind': self._attendee_kind(person),
                'can_check_in': allowed, 'reason': None if allowed else REASONS.get(why),
                'write_date': fields.Datetime.to_string(person.write_date),
            })

        at_church = None
        locations = self.env['church.location'].sudo().search([('active', '=', True)])
        if latitude is not None and longitude is not None:
            for loc in locations.filtered(lambda l: l._has_coordinates()):
                res, _d = rules.check_location(loc.latitude, loc.longitude, loc.geofence_radius_m,
                                               latitude, longitude, accuracy)
                if res == 'ok':
                    at_church = loc.name
                    break
        return {
            'success': True,
            'server_time': fields.Datetime.to_string(at),
            'member_id': partner.id,
            'at_church': at_church,
            'open': open_now,
            'upcoming': upcoming[:10],
            'household': household,
            'locations': [{'location_id': l.id, 'name': l.name,
                           'reminders': l.geofence_enabled} for l in locations],
        }

    @api.model
    def app_attendance_check_in(self, items, latitude=None, longitude=None, accuracy=None,
                                captured_at=None, device_id=None, idempotency_key=None,
                                offline=False):
        """Check the signed-in member and/or their dependents in.

        items: [{'member_id', 'service_id'}]. captured_at ('YYYY-MM-DD HH:MM:SS'
        UTC) matters only for offline attempts sent later.
        """
        partner = self._member_from_session()
        if not partner:
            return {'success': False, 'error': 'sign_in_required'}
        if not isinstance(items, list) or not items or len(items) > 30:
            return {'success': False, 'error': 'Choose who to check in.'}
        replay = self._replay(idempotency_key, items)
        if replay:
            return dict(replay, success=True)
        captured = None
        if captured_at:
            try:
                # Accept 'YYYY-MM-DD HH:MM:SS' and ISO 8601 UTC ('...T...Z').
                text = str(captured_at).replace('T', ' ').rstrip('Z').split('.')[0][:19]
                captured = fields.Datetime.to_datetime(text)
            except (TypeError, ValueError):
                captured = None
        family = any(int(i.get('member_id') or 0) != partner.id for i in items)
        result = self._check_in(
            items, 'geofence_family' if family else 'geofence_self', acting_partner=partner,
            latitude=latitude, longitude=longitude, accuracy=accuracy,
            captured_at=captured, offline=bool(offline), device_id=device_id,
            idempotency_key=idempotency_key)
        return dict(result, success=True)

    @api.model
    def app_attendance_my_history(self, limit=50):
        partner = self._member_from_session()
        if not partner:
            return {'success': False, 'error': 'sign_in_required'}
        records = self.sudo().search([('member_id', '=', partner.id),
                                      ('status', 'not in', ('removed', 'cancelled'))],
                                     order='check_in_time desc', limit=min(int(limit or 50), 200))
        return {'success': True, 'attendance': [{
            'attendance_id': r.id, 'service_id': r.event_id.id, 'service_name': r.event_id.name,
            'check_in_time': fields.Datetime.to_string(r.check_in_time),
            'status': r.status, 'method': r.method} for r in records]}

    # ── Staff endpoints (staff session token required) ─────────

    @api.model
    def _require_staff(self):
        staff = self._staff_from_session()
        return staff or None

    @api.model
    def app_attendance_staff_services(self, days_back=1, days_ahead=1):
        """Services around today with counts, for the staff Attendance screen."""
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        at = _now()
        services = self.env['church.service'].sudo().search([
            ('attendance_enabled', '=', True),
            ('date_start', '>=', at - timedelta(days=days_back or 0)),
            ('date_start', '<=', at + timedelta(days=days_ahead or 0)),
        ], order='date_start asc, id asc')
        return {'success': True, 'services': [dict(
            self._service_counts(s), service_id=s.id, name=s.name, state=s._availability(at),
            cancelled=s.cancelled, date_start=fields.Datetime.to_string(s.date_start),
            **s._local_labels()) for s in services]}

    @api.model
    def _service_counts(self, service):
        records = self.sudo().search([('event_id', '=', service.id),
                                      ('status', 'not in', ('removed', 'cancelled'))])
        return {
            'total': len(records),
            'members': len(records.filtered(lambda r: r.attendee_kind == 'member')),
            'children': len(records.filtered(lambda r: r.attendee_kind == 'child')),
            'guests': len(records.filtered(lambda r: r.attendee_kind == 'guest')),
            'families': len(records.mapped('family_id')),
            'late': len(records.filtered('is_late')),
        }

    @api.model
    def app_attendance_service_detail(self, service_id, kind=None, query=''):
        """One service's attendance list. kind: member/child/guest or None for all."""
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        service = self.env['church.service'].sudo().browse(int(service_id)).exists()
        if not service:
            return {'success': False, 'error': REASONS['not_found']}
        domain = [('event_id', '=', service.id), ('status', '!=', 'removed')]
        if kind in ('member', 'child', 'guest'):
            domain.append(('attendee_kind', '=', kind))
        if query:
            domain.append(('member_id.name', 'ilike', query))
        records = self.sudo().search(domain, order='check_in_time desc')
        methods = dict(self._fields['method'].selection)
        statuses = dict(self._fields['status'].selection)
        return {'success': True, 'counts': self._service_counts(service),
                'service': dict(service_id=service.id, name=service.name,
                                state=service._availability(), **service._local_labels()),
                'attendance': [{
                    'attendance_id': r.id, 'member_id': r.member_id.id, 'name': r.member_id.name,
                    'kind': r.attendee_kind, 'family': r.family_id.name or '',
                    'check_in_time': fields.Datetime.to_string(r.check_in_time),
                    'method': r.method, 'method_label': methods.get(r.method, ''),
                    'status': r.status, 'status_label': statuses.get(r.status, ''),
                    'is_late': r.is_late, 'location_verified': r.location_verified,
                    'checked_in_by': r.checked_in_by_staff_id.name or r.checked_in_by_partner_id.name or '',
                    'notes': r.notes or '',
                } for r in records]}

    @api.model
    def app_attendance_search_people(self, query, service_id=None):
        """Members, families and visitors for manual check-in."""
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        query = (query or '').strip()
        if len(query) < 2:
            return {'success': True, 'people': []}
        Partner = self.env['res.partner'].sudo()
        people = Partner.search(['|', '|', ('name', 'ilike', query), ('member_number', 'ilike', query),
                                 ('phone', 'ilike', query),
                                 '|', ('is_member', '=', True), ('visitor_stage', '!=', False)], limit=25)
        families = people.mapped('family_id')
        if families:
            people |= Partner.search([('family_id', 'in', families.ids)], limit=60)
        checked = set()
        if service_id:
            checked = set(self.sudo().search([
                ('event_id', '=', int(service_id)), ('member_id', 'in', people.ids),
                ('status', 'not in', ('removed', 'cancelled'))]).mapped('member_id').ids)
        return {'success': True, 'people': [{
            'member_id': p.id, 'name': p.name, 'member_number': p.member_number or '',
            'family_id': p.family_id.id or False, 'family': p.family_id.name or '',
            'kind': self._attendee_kind(p), 'checked_in': p.id in checked,
        } for p in people.sorted('name')]}

    @api.model
    def app_attendance_staff_check_in(self, service_id, member_ids, notes=None, idempotency_key=None):
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        items = [{'member_id': m, 'service_id': service_id} for m in (member_ids or [])][:60]
        if not items:
            return {'success': False, 'error': 'Choose who to check in.'}
        replay = self._replay(idempotency_key, items)
        if replay:
            return dict(replay, success=True)
        method = 'admin_manual' if staff.staff_role == 'admin' else 'staff_manual'
        return dict(self._check_in(items, method, acting_staff=staff, notes=notes,
                                   idempotency_key=idempotency_key), success=True)

    @api.model
    def app_attendance_add_guest(self, service_id, name, phone=None, idempotency_key=None):
        """Register a first-time guest as a visitor and check them in."""
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        name = (name or '').strip()
        if len(name) < 2:
            return {'success': False, 'error': "Enter the guest's name."}
        service = self.env['church.service'].sudo().browse(int(service_id)).exists()
        if not service or not service.guest_checkin_enabled:
            return {'success': False, 'error': REASONS['guests_off']}
        guest = self.env['res.partner'].sudo().create({
            'name': name, 'phone': (phone or '').strip() or False,
            'visitor_stage': 'new', 'is_member': False,
        })
        return dict(self._check_in([{'member_id': guest.id, 'service_id': service.id}],
                                   'admin_manual' if staff.staff_role == 'admin' else 'staff_manual',
                                   acting_staff=staff, idempotency_key=idempotency_key),
                    success=True, guest_id=guest.id)

    @api.model
    def app_attendance_update(self, attendance_id, status=None, notes=None, reason=None):
        """Change status (present/late/excused/removed) or notes. Removing needs a reason."""
        staff = self._require_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        record = self.sudo().browse(int(attendance_id)).exists()
        if not record:
            return {'success': False, 'error': 'Attendance not found.'}
        vals = {}
        if status:
            if status not in dict(self._fields['status'].selection):
                return {'success': False, 'error': 'Unknown status.'}
            if status == 'removed' and not (reason or '').strip():
                return {'success': False, 'error': 'Give a reason for removing this attendance.'}
            vals['status'] = status
            vals['is_late'] = status == 'late' or (record.is_late and status not in ('present', 'excused'))
        if notes is not None:
            vals['notes'] = notes or False
        if not vals:
            return {'success': True, 'attendance_id': record.id}
        before = record.status
        record.write(vals)
        self._log('removed' if vals.get('status') == 'removed' else 'edited', attendance=record,
                  actor_staff=staff, details=(reason or '').strip()
                  or (f'{before} -> {vals["status"]}' if 'status' in vals else 'notes'))
        return {'success': True, 'attendance_id': record.id, 'status': record.status}

    # ── Existing entry point, kept for older app versions ───────

    @api.model
    def app_check_in(self, event_id=None, member_id=None, requester_partner_id=None,
                     requester_staff_id=None, service_id=None, member_code=None, method=None):
        """Older apps: self check-in, or usher QR / typed code / list tap.

        Routed through the same check-in path. Members checking themselves in
        without a location count as 'member_manual', allowed only when the
        event permits check-in without location.
        """
        ResPartner = self.env['res.partner']
        mode, scope = ResPartner._church_caller_scope(requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}
        if member_code and not member_id:
            member = self._member_from_code(member_code)
            if not member:
                return {'success': False, 'error': 'No member found for this code'}
            member_id = member.id
        if not member_id:
            return {'success': False, 'error': 'Missing member'}
        if mode == 'self' and member_id != scope:
            return {'success': False, 'error': 'You can only check yourself in'}
        Service = self.env['church.service'].sudo()
        if service_id:
            service = Service.browse(int(service_id)).exists()
        elif event_id:
            service = Service._from_legacy_onevoice_event(int(event_id))
        else:
            service = Service
        if not service:
            return {'success': False, 'error': 'Service not found'}
        member_name = ResPartner.sudo().browse(member_id).name or ''
        items = [{'member_id': member_id, 'service_id': service.id}]

        if mode == 'self':
            if service.geofence_required and service._location_result(None, None, None)[0] != 'not_required':
                return {'success': False, 'error': 'Update the app to check in at the church.'}
            result = self._check_in(items, 'member_manual',
                                    acting_partner=ResPartner.sudo().browse(scope))
        else:
            employee = self.env['hr.employee'].sudo().browse(requester_staff_id)
            legacy = method if method in ('qr', 'kiosk') else \
                ('admin_manual' if employee.staff_role == 'admin' else 'staff_manual')
            result = self._check_in(items, legacy, acting_staff=employee)

        if result['successful']:
            return {'success': True, 'attendance_id': result['successful'][0]['attendance_id'],
                    'already_checked_in': False, 'member_name': member_name}
        if result['already']:
            return {'success': True, 'attendance_id': result['already'][0]['attendance_id'],
                    'already_checked_in': True, 'member_name': member_name}
        return {'success': False, 'error': result['failed'][0]['message'] if result['failed']
                else REASONS['not_open'], 'member_name': member_name}
