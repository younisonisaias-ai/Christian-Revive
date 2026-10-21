"""Pastoral visit requests: a member asks for a pastor's visit for themselves
or someone in their household, suggests times, and the pastor confirms a
time, marks it visited (which records a pastoral care note) or declines.

Requests go to the member's assigned pastor; senior pastors and admins see
them all and can hand one to another pastor.
"""
from datetime import timedelta

import pytz

from odoo import api, fields, models

from .pastor_alerts import _send_fcm

REASONS = [
    ('home', 'Home visit'),
    ('hospital', 'Hospital visit'),
    ('prayer', 'Prayer'),
    ('counseling', 'Counseling'),
    ('bereavement', 'Bereavement'),
    ('blessing', 'New baby / blessing'),
    ('other', 'Other'),
]
PARTS_OF_DAY = [('morning', 'Morning'), ('afternoon', 'Afternoon'), ('evening', 'Evening')]
OPEN_STATES = ('requested', 'scheduled')
# Pastoral note type recorded when a visit is done.
NOTE_TYPES = {'hospital': 'hospital', 'bereavement': 'bereavement', 'counseling': 'counseling',
              'prayer': 'prayer'}


class ChurchVisitRequest(models.Model):
    _name = 'church.visit.request'
    _description = 'Pastoral visit request'
    _order = 'is_urgent desc, create_date desc'

    name = fields.Char(compute='_compute_name', store=True)
    member_id = fields.Many2one('res.partner', string='Visit', required=True, index=True,
                                help='The person to visit.')
    requested_by_id = fields.Many2one('res.partner', string='Requested by', required=True, index=True)
    reason = fields.Selection(REASONS, required=True, default='home')
    place = fields.Selection([('home', 'Home'), ('hospital', 'Hospital'), ('other', 'Other')],
                             required=True, default='home')
    address = fields.Char(help='Home address, or hospital name and ward.')
    phone = fields.Char()
    note = fields.Text()
    is_urgent = fields.Boolean(string='Urgent')
    pref1_date = fields.Date(string='Preferred day 1')
    pref1_part = fields.Selection(PARTS_OF_DAY, string='Time 1')
    pref2_date = fields.Date(string='Preferred day 2')
    pref2_part = fields.Selection(PARTS_OF_DAY, string='Time 2')
    pref3_date = fields.Date(string='Preferred day 3')
    pref3_part = fields.Selection(PARTS_OF_DAY, string='Time 3')
    state = fields.Selection([
        ('requested', 'Requested'),
        ('scheduled', 'Scheduled'),
        ('visited', 'Visited'),
        ('declined', 'Declined'),
        ('cancelled', 'Cancelled'),
    ], default='requested', required=True, index=True)
    pastor_id = fields.Many2one('hr.employee', string='Pastor', index=True,
                                domain=[('staff_role', 'in', ('pastor', 'admin'))])
    scheduled_at = fields.Datetime(string='Visit on')
    pastor_message = fields.Text(string='Message to the member')
    outcome = fields.Text()
    care_note_id = fields.Many2one('pastoral.care.note', string='Pastoral note', readonly=True)
    scheduled_on = fields.Datetime(string='Booked on', readonly=True)
    reminded_day = fields.Boolean(readonly=True, copy=False)
    reminded_hour = fields.Boolean(readonly=True, copy=False)

    @api.depends('member_id', 'reason')
    def _compute_name(self):
        labels = dict(REASONS)
        for rec in self:
            rec.name = '%s · %s' % (labels.get(rec.reason, ''), rec.member_id.name or '')

    # ── Helpers ─────────────────────────────────────────────────

    def _preferred(self):
        self.ensure_one()
        return [{'date': fields.Date.to_string(d), 'part': p or ''}
                for d, p in ((self.pref1_date, self.pref1_part), (self.pref2_date, self.pref2_part),
                             (self.pref3_date, self.pref3_part)) if d]

    def _for_app(self):
        self.ensure_one()
        return {
            'id': self.id,
            'member_id': self.member_id.id,
            'member_name': self.member_id.name or '',
            'requested_by': self.requested_by_id.name or '',
            'reason': self.reason,
            'place': self.place,
            'address': self.address or '',
            'phone': self.phone or '',
            'note': self.note or '',
            'is_urgent': self.is_urgent,
            'preferred': self._preferred(),
            'state': self.state,
            'pastor_id': self.pastor_id.id or False,
            'pastor_name': self.pastor_id.name or '',
            'scheduled_at': fields.Datetime.to_string(self.scheduled_at) if self.scheduled_at else False,
            'pastor_message': self.pastor_message or '',
            'outcome': self.outcome or '',
            'created': fields.Datetime.to_string(self.create_date),
        }

    @api.model
    def _household(self, partner):
        """The member and everyone in their household."""
        if partner.family_id:
            return partner.family_id.member_ids | partner
        return partner

    def _local_when(self):
        """'Fri 23 Oct at 5:00 PM' in the church's time zone."""
        self.ensure_one()
        if not self.scheduled_at:
            return ''
        tz = self.env['church.service.schedule']._church_tz()
        local = pytz.utc.localize(fields.Datetime.to_datetime(self.scheduled_at)).astimezone(tz)
        hour = local.hour % 12 or 12
        return '%s %d %s at %d:%02d %s' % (local.strftime('%a'), local.day, local.strftime('%b'),
                                           hour, local.minute, 'AM' if local.hour < 12 else 'PM')

    def _push(self, tokens, title, body, data):
        tokens = [t for t in set(tokens) if t]
        if not tokens:
            return
        sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
        self.env.cr.postcommit.add(lambda: _send_fcm(sa_path, tokens, title, body, data))

    def _tell_member(self, title, body):
        """Push to the member who asked (and the person visited, if different)."""
        people = (self.requested_by_id | self.member_id).filtered('app_fcm_token')
        self._push(people.mapped('app_fcm_token'), title, body, {'type': 'visit_request', 'id': self.id})

    def _tell_pastor(self, title, body):
        pastor = self.pastor_id
        if pastor and pastor.is_app_active and pastor.app_fcm_token:
            self._push([pastor.app_fcm_token], title, body,
                       {'type': 'pastor_alert', 'kind': 'visit', 'id': self.id})

    @api.model
    def _cron_visit_reminders(self):
        """The day before (for visits booked well ahead) and about an hour
        before a booked visit, remind the member and the pastor."""
        now = fields.Datetime.now()
        booked = self.sudo().search([('state', '=', 'scheduled'), ('scheduled_at', '>', now),
                                     ('scheduled_at', '<=', now + timedelta(hours=26))])
        for visit in booked:
            ahead = visit.scheduled_at - now
            where = visit.member_id.name or ''
            pastor = visit.pastor_id.name or 'Your pastor'
            if ahead <= timedelta(minutes=75):
                if not visit.reminded_hour:
                    visit.write({'reminded_hour': True, 'reminded_day': True})
                    visit._tell_member('Pastor visit soon', '%s will visit at %s.'
                                       % (pastor, visit._local_when().split(' at ')[-1]))
                    visit._tell_pastor('Visit soon', 'Visit %s at %s.'
                                       % (where, visit._local_when().split(' at ')[-1]))
            elif ahead > timedelta(hours=3) and not visit.reminded_day and                     visit.scheduled_on and visit.scheduled_at - visit.scheduled_on > timedelta(hours=26):
                visit.reminded_day = True
                visit._tell_member('Pastor visit tomorrow', '%s will visit on %s.' % (pastor, visit._local_when()))
                visit._tell_pastor('Visit tomorrow', 'Visit %s on %s.' % (where, visit._local_when()))

    @api.model
    def _staff(self, requester_staff_id):
        """(mode, employee) for a staff caller, or (None, error)."""
        mode, _scope = self.env['res.partner']._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return None, 'Only pastors can handle visit requests'
        return mode, self.env['hr.employee'].sudo().browse(int(requester_staff_id))

    def _staff_may(self, mode, employee):
        self.ensure_one()
        return mode == 'all' or self.pastor_id == employee

    # ── Member endpoints ────────────────────────────────────────

    @api.model
    def app_visit_options(self, requester_partner_id=None):
        """Who the member may ask for, with addresses and phones to prefill."""
        mode, scope = self.env['res.partner']._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Please sign in as a member'}
        me = self.env['res.partner'].sudo().browse(scope)
        people = self._household(me)
        return {'success': True, 'people': [{
            'id': p.id,
            'name': p.name,
            'is_me': p == me,
            'relationship': p.family_relationship or '',
            'address': ', '.join(x for x in (p.street, p.city) if x),
            'phone': p.phone or me.phone or '',
        } for p in people.sorted(lambda p: (p != me, p.name or ''))]}

    @api.model
    def app_request_visit(self, vals, requester_partner_id=None):
        mode, scope = self.env['res.partner']._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Please sign in as a member'}
        me = self.env['res.partner'].sudo().browse(scope)
        vals = dict(vals or {})
        member = self.env['res.partner'].sudo().browse(int(vals.get('member_id') or me.id)).exists()
        if not member or member not in self._household(me):
            return {'success': False, 'error': 'You can ask for a visit for yourself or your household'}
        if vals.get('reason') not in dict(REASONS):
            return {'success': False, 'error': 'Choose what the visit is for'}
        place = vals.get('place') if vals.get('place') in ('home', 'hospital', 'other') else 'home'
        if place != 'home' and not (vals.get('address') or '').strip():
            return {'success': False, 'error': 'Tell the pastor where to come'}
        record = {
            'member_id': member.id,
            'requested_by_id': me.id,
            'reason': vals['reason'],
            'place': place,
            'address': (vals.get('address') or '').strip()[:300],
            'phone': (vals.get('phone') or '').strip()[:40],
            'note': (vals.get('note') or '').strip()[:2000],
            'is_urgent': bool(vals.get('is_urgent')),
        }
        today = fields.Date.context_today(self)
        for i, slot in enumerate((vals.get('preferred') or [])[:3], start=1):
            day = fields.Date.to_date(slot.get('date')) if slot.get('date') else None
            if day and day >= today:
                record['pref%d_date' % i] = day
                part = slot.get('part')
                record['pref%d_part' % i] = part if part in dict(PARTS_OF_DAY) else False
        # The member's assigned pastor; without one, senior pastors pick it up.
        assigned = self.env['pastor.assignment'].sudo().search([('member_id', '=', member.id)], limit=1)
        if assigned:
            record['pastor_id'] = assigned.pastor_id.id
        request = self.sudo().create(record)
        labels = dict(REASONS)
        title = ('URGENT: ' if request.is_urgent else '') + 'Visit requested'
        body = '%s asks for a %s%s' % (
            me.name, labels[request.reason].lower(),
            '' if member == me else ' for %s' % member.name)
        self.env['church.alerts'].notify_pastors(member, title, body, 'visit', request.id)
        return {'success': True, 'request': request._for_app()}

    @api.model
    def app_my_visit_requests(self, requester_partner_id=None):
        mode, scope = self.env['res.partner']._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Please sign in as a member'}
        records = self.sudo().search(['|', ('requested_by_id', '=', scope), ('member_id', '=', scope)],
                                     order='create_date desc', limit=50)
        return {'success': True, 'requests': [r._for_app() for r in records]}

    @api.model
    def app_cancel_visit(self, request_id, requester_partner_id=None):
        mode, scope = self.env['res.partner']._church_caller_scope(requester_partner_id=requester_partner_id)
        request = self.sudo().browse(int(request_id or 0)).exists()
        if mode != 'self' or not request or scope not in (request.requested_by_id.id, request.member_id.id):
            return {'success': False, 'error': 'Request not found'}
        if request.state not in OPEN_STATES:
            return {'success': False, 'error': 'This request is already closed'}
        request.state = 'cancelled'
        if request.pastor_id:
            self.env['church.alerts'].notify_pastors(
                request.member_id, 'Visit cancelled',
                '%s cancelled the visit request' % request.requested_by_id.name, 'visit', request.id)
        return {'success': True, 'request': request._for_app()}

    # ── Pastor endpoints ────────────────────────────────────────

    @api.model
    def app_visit_requests(self, status='open', requester_staff_id=None):
        """Open (requested + scheduled) or closed requests the pastor handles.
        Senior pastors and admins see every request."""
        mode, employee = self._staff(requester_staff_id)
        if not mode:
            return {'success': False, 'error': employee}
        domain = [('state', 'in', OPEN_STATES)] if status == 'open' else \
            [('state', 'not in', OPEN_STATES)] if status == 'closed' else []
        if mode == 'assigned':
            domain.append(('pastor_id', '=', employee.id))
        records = self.sudo().search(domain, order='is_urgent desc, scheduled_at asc, create_date desc',
                                     limit=200)
        return {'success': True, 'can_assign': mode == 'all', 'requests': [r._for_app() for r in records]}

    @api.model
    def app_schedule_visit(self, request_id, scheduled_at, message='', requester_staff_id=None):
        mode, employee = self._staff(requester_staff_id)
        request = self.sudo().browse(int(request_id or 0)).exists()
        if not mode or not request or not request._staff_may(mode, employee):
            return {'success': False, 'error': 'Request not found'}
        if request.state not in OPEN_STATES:
            return {'success': False, 'error': 'This request is already closed'}
        when = fields.Datetime.to_datetime(scheduled_at) if scheduled_at else None
        if not when:
            return {'success': False, 'error': 'Choose the day and time of the visit'}
        request.write({
            'state': 'scheduled',
            'scheduled_at': when,
            'scheduled_on': fields.Datetime.now(),
            'reminded_day': False,
            'reminded_hour': False,
            'pastor_id': request.pastor_id.id or employee.id,
            'pastor_message': (message or '').strip()[:1000],
        })
        request._tell_member('Visit confirmed', '%s will visit on %s.'
                             % (request.pastor_id.name or 'Your pastor', request._local_when()))
        return {'success': True, 'request': request._for_app()}

    @api.model
    def app_complete_visit(self, request_id, outcome='', requester_staff_id=None):
        """Mark visited; the visit is also kept as a pastoral care note."""
        mode, employee = self._staff(requester_staff_id)
        request = self.sudo().browse(int(request_id or 0)).exists()
        if not mode or not request or not request._staff_may(mode, employee):
            return {'success': False, 'error': 'Request not found'}
        if request.state not in OPEN_STATES:
            return {'success': False, 'error': 'This request is already closed'}
        labels = dict(REASONS)
        note = self.env['pastoral.care.note'].sudo().create({
            'member_id': request.member_id.id,
            'author_id': (request.pastor_id or employee).id,
            'note_type': NOTE_TYPES.get(request.reason, 'visit'),
            'content': '%s (requested by %s).%s' % (
                labels[request.reason], request.requested_by_id.name,
                (' ' + request.note) if request.note else ''),
            'outcome': (outcome or '').strip() or False,
        })
        request.write({'state': 'visited', 'outcome': (outcome or '').strip(), 'care_note_id': note.id,
                       'pastor_id': request.pastor_id.id or employee.id})
        return {'success': True, 'request': request._for_app()}

    @api.model
    def app_decline_visit(self, request_id, message='', requester_staff_id=None):
        mode, employee = self._staff(requester_staff_id)
        request = self.sudo().browse(int(request_id or 0)).exists()
        if not mode or not request or not request._staff_may(mode, employee):
            return {'success': False, 'error': 'Request not found'}
        if request.state not in OPEN_STATES:
            return {'success': False, 'error': 'This request is already closed'}
        if not (message or '').strip():
            return {'success': False, 'error': 'Add a short message for the member'}
        request.write({'state': 'declined', 'pastor_message': message.strip()[:1000],
                       'pastor_id': request.pastor_id.id or employee.id})
        request._tell_member('About your visit request', message.strip()[:120])
        return {'success': True, 'request': request._for_app()}

    @api.model
    def app_assign_visit(self, request_id, pastor_id, requester_staff_id=None):
        """Senior pastor or admin: hand a request to another pastor."""
        mode, employee = self._staff(requester_staff_id)
        request = self.sudo().browse(int(request_id or 0)).exists()
        if mode != 'all' or not request:
            return {'success': False, 'error': 'Only a senior pastor or admin can reassign'}
        pastor = self.env['hr.employee'].sudo().browse(int(pastor_id or 0)).exists()
        if not pastor or pastor.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Choose a pastor'}
        request.pastor_id = pastor
        if pastor.app_fcm_token and pastor.is_app_active:
            sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
            tokens = [pastor.app_fcm_token]
            data = {'type': 'pastor_alert', 'kind': 'visit', 'id': request.id}
            body = 'Visit for %s' % request.member_id.name
            self.env.cr.postcommit.add(lambda: _send_fcm(sa_path, tokens, 'Visit assigned to you', body, data))
        return {'success': True, 'request': request._for_app()}
