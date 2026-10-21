"""Pastoral care helpers for pastors and members.

* Absence follow-ups: once a day, members who came to church in the last
  four months but have not checked in for three weeks get a follow-up for
  their assigned pastor (a senior pastor when none is assigned), with one
  summary alert per pastor. At most one automatic follow-up a month each.
* "My pastor": a member's assigned pastor, for the profile and a Call button.
* The pastor's week: booked visits, follow-ups, cell group meetings and
  services, day by day.
* The care report: per pastor, visits and calls done, follow-ups still open
  and assigned members nobody has contacted lately.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

from .church_dashboard import ACTIVE_STATUSES
from .pastor_alerts import _send_fcm

ABSENT_DAYS = 21
STILL_COMING_DAYS = 120
AUTO_FOLLOW_UP_EVERY_DAYS = 30
VISIT_NOTE_TYPES = ('visit', 'hospital', 'bereavement')
WEEKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']


class ResPartnerCare(models.Model):
    _inherit = 'res.partner'

    absence_followup_date = fields.Date(
        string='Absence follow-up created', readonly=True, copy=False,
        help='Last time an automatic follow-up was created because this member stopped coming.')


class PastorAssignmentCare(models.Model):
    _inherit = 'pastor.assignment'

    @api.model
    def _pastor_of(self, member):
        return self.sudo().search([('member_id', '=', member.id)], limit=1).pastor_id

    @api.model
    def app_member_care_info(self, member_id=None, requester_partner_id=None, requester_staff_id=None):
        """The member's pastor (and, for staff, whether they are on the
        prayer team) for the member profile."""
        Partner = self.env['res.partner']
        mode, scope = Partner._church_caller_scope(requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}
        member = Partner.sudo().browse(int(member_id or scope or 0)).exists()
        if not member:
            return {'success': False, 'error': 'Member not found'}
        if mode == 'self':
            me = Partner.sudo().browse(scope)
            household = me.family_id.member_ids | me if me.family_id else me
            if member not in household:
                return {'success': False, 'error': 'Not authorized'}
        elif mode == 'assigned' and member.id not in (scope or []):
            return {'success': False, 'error': 'Not authorized'}
        pastor = self._pastor_of(member)
        info = {'success': True, 'pastor': {
            'id': pastor.id,
            'name': pastor.name or '',
            'phone': pastor.mobile_phone or pastor.work_phone or '',
        } if pastor else False}
        if mode != 'self':
            info['prayer_team'] = bool(member.prayer_team)
        return info


class ChurchCareReports(models.AbstractModel):
    _inherit = 'church.dashboard'

    # ── Absence follow-ups ──────────────────────────────────────

    @api.model
    def _cron_absence_followups(self):
        if not self.env['church.plan']._allows('enterprise'):
            return
        Attendance = self.env['church.event.attendance'].sudo()
        now = fields.Datetime.now()
        # Only when the church is actually taking attendance.
        if not Attendance.search_count([('check_in_time', '>=', now - timedelta(days=7))]):
            return
        Partner = self.env['res.partner'].sudo()
        members = Partner.search([('is_member', '=', True), ('membership_status', 'in', ACTIVE_STATUSES)])
        last_seen = dict(Attendance._read_group(
            [('member_id', 'in', members.ids or [0])], groupby=['member_id'], aggregates=['check_in_time:max']))
        today = fields.Date.context_today(self)
        Assignment = self.env['pastor.assignment']
        seniors = self.env['hr.employee'].sudo().search(
            [('staff_role', '=', 'pastor'), ('is_senior_pastor', '=', True), ('is_app_active', '=', True)], limit=1)
        per_pastor = defaultdict(list)
        for member in members:
            last = last_seen.get(member)
            if not last or last < now - timedelta(days=STILL_COMING_DAYS) or \
                    last >= now - timedelta(days=ABSENT_DAYS):
                continue
            if member.absence_followup_date and \
                    member.absence_followup_date > today - timedelta(days=AUTO_FOLLOW_UP_EVERY_DAYS):
                continue
            pastor = Assignment._pastor_of(member) or seniors
            if not pastor:
                continue
            self.env['pastoral.care.note'].sudo().create({
                'member_id': member.id,
                'author_id': pastor.id,
                'note_type': 'call',
                'content': 'Has not been at church for 3 weeks (last seen %s). Please call or visit.'
                           % fields.Date.to_string(last.date()),
                'follow_up_date': today,
                'follow_up_assigned_to_id': pastor.id,
            })
            member.absence_followup_date = today
            per_pastor[pastor].append(member.name)
        sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
        for pastor, names in per_pastor.items():
            if not (pastor.is_app_active and pastor.app_fcm_token):
                continue
            count = len(names)
            body = ('%s has' % names[0] if count == 1 else '%d members have' % count) + \
                ' missed church for 3 weeks. A follow-up was added for you.'
            tokens = [pastor.app_fcm_token]
            data = {'type': 'pastor_alert', 'kind': 'absent', 'id': 0}
            self.env.cr.postcommit.add(
                lambda t=tokens, b=body: _send_fcm(sa_path, t, 'Members missing church', b, data))

    # ── The pastor's week ───────────────────────────────────────

    @api.model
    def app_pastor_week(self, start=None, requester_staff_id=None):
        """Seven days from [start] (YYYY-MM-DD, default today): the pastor's
        booked visits, follow-ups, cell group meetings and church services."""
        mode, scope = self.env['res.partner']._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Only pastors have a week plan'}
        me = self.env['hr.employee'].sudo().browse(int(requester_staff_id))
        tz = self.env['church.service.schedule']._church_tz()
        first = fields.Date.to_date(start) if start else datetime.now(tz).date()
        days = [first + timedelta(days=i) for i in range(7)]
        begin = tz.localize(datetime.combine(days[0], time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = begin + timedelta(days=7)

        def local(dt):
            return pytz.utc.localize(dt).astimezone(tz)

        items = defaultdict(list)
        for visit in self.env['church.visit.request'].sudo().search(
                [('state', '=', 'scheduled'), ('scheduled_at', '>=', begin), ('scheduled_at', '<', end),
                 ('pastor_id', '=', me.id)]):
            at = local(visit.scheduled_at)
            items[at.date()].append({'kind': 'visit', 'id': visit.id, 'time': at.strftime('%H:%M'),
                                     'title': 'Visit %s' % visit.member_id.name,
                                     'subtitle': visit.address or '', 'member_id': visit.member_id.id})
        Note = self.env['pastoral.care.note'].sudo()
        for note in Note.search([('follow_up_done', '=', False), ('follow_up_date', '>=', days[0]),
                                 ('follow_up_date', '<=', days[-1]),
                                 '|', ('follow_up_assigned_to_id', '=', me.id),
                                 '&', ('follow_up_assigned_to_id', '=', False), ('author_id', '=', me.id)]):
            items[note.follow_up_date].append({'kind': 'follow_up', 'id': note.id, 'time': '',
                                               'title': 'Follow up %s' % note.member_id.name,
                                               'subtitle': (note.content or '')[:80],
                                               'member_id': note.member_id.id})
        Group = self.env['cell.group'].sudo()
        groups = Group.search([]) if mode == 'all' else Group.search(
            ['|', ('leader_id', 'in', scope or [0]), ('member_ids', 'in', scope or [0])])
        for day in days:
            weekday = WEEKDAYS[day.weekday()]
            for group in groups.filtered(lambda g: g.meeting_day == weekday):
                items[day].append({'kind': 'cell_group', 'id': group.id, 'time': group.meeting_time or '',
                                   'title': group.name, 'subtitle': group.meeting_location or ''})
        for service in self.env['church.service'].sudo().search(
                [('is_active', '=', True), ('date_start', '>=', begin), ('date_start', '<', end)]):
            at = local(service.date_start)
            items[at.date()].append({'kind': 'service', 'id': service.id, 'time': at.strftime('%H:%M'),
                                     'title': service.name, 'subtitle': service.location or ''})
        return {'success': True, 'days': [{
            'date': fields.Date.to_string(day),
            'items': sorted(items[day], key=lambda i: (i['time'] == '', i['time'])),
        } for day in days]}

    # ── Care report ─────────────────────────────────────────────

    @api.model
    def app_care_report(self, days=90, requester_staff_id=None):
        """Per pastor: visits and calls in the period, follow-ups still open,
        and assigned members nobody has contacted in the period."""
        mode, _scope = self.env['res.partner']._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Only pastors can see the care report'}
        days = max(7, min(int(days or 90), 365))
        since_date = fields.Date.context_today(self) - timedelta(days=days)
        since = datetime.combine(since_date, time.min)
        Employee = self.env['hr.employee'].sudo()
        pastors = Employee.search([('staff_role', '=', 'pastor'), ('is_app_active', '=', True)]) \
            if mode == 'all' else Employee.browse(int(requester_staff_id))
        Note = self.env['pastoral.care.note'].sudo()
        Visit = self.env['church.visit.request'].sudo()
        Assignment = self.env['pastor.assignment'].sudo()
        rows, quiet = [], []
        for pastor in pastors:
            members = Assignment.search([('pastor_id', '=', pastor.id)]).mapped('member_id')
            notes = Note.search([('author_id', '=', pastor.id), ('date', '>=', since_date)])
            contacted = set(notes.mapped('member_id').ids)
            contacted |= set(Visit.search([('pastor_id', '=', pastor.id), ('state', '=', 'visited'),
                                           ('write_date', '>=', since)]).mapped('member_id').ids)
            not_contacted = members.filtered(lambda m: m.id not in contacted)
            rows.append({
                'pastor_id': pastor.id,
                'pastor': pastor.name,
                'members': len(members),
                'visits': len(notes.filtered(lambda n: n.note_type in VISIT_NOTE_TYPES)),
                'calls': len(notes.filtered(lambda n: n.note_type == 'call')),
                'follow_ups_open': Note.search_count([
                    ('follow_up_done', '=', False), ('follow_up_date', '!=', False),
                    '|', ('follow_up_assigned_to_id', '=', pastor.id),
                    '&', ('follow_up_assigned_to_id', '=', False), ('author_id', '=', pastor.id)]),
                'not_contacted': len(not_contacted),
            })
            for member in not_contacted:
                last = Note.search([('member_id', '=', member.id)], order='date desc', limit=1)
                quiet.append({'id': member.id, 'name': member.name, 'pastor': pastor.name,
                              'phone': member.phone or '',
                              'last_contact': fields.Date.to_string(last.date) if last else False})
        rows.sort(key=lambda r: -r['not_contacted'])
        quiet.sort(key=lambda q: (q['last_contact'] or '', q['name']))
        return {'success': True, 'days': days, 'pastors': rows, 'not_contacted': quiet[:100]}
