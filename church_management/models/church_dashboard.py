from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import models, fields, api

# Membership statuses that count as "active members" on the dashboard.
ACTIVE_STATUSES = ('new_convert', 'member', 'worker', 'leader')


class ChurchDashboard(models.AbstractModel):
    """Numbers for the Church Management dashboard in the app.

    Admins and senior pastors see the whole church; an associate pastor sees
    the same cards for their assigned members only. Giving totals are only
    returned to admins (same rule as the finance reports).
    """
    _name = 'church.dashboard'
    _description = 'Church Management Dashboard'

    @api.model
    def app_get_dashboard(self, requester_staff_id=None, weeks=8):
        Partner = self.env['res.partner'].sudo()
        mode, scope = Partner._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        employee = self.env['hr.employee'].sudo().browse(int(requester_staff_id))

        today = fields.Date.context_today(self)
        now = fields.Datetime.now()

        member_domain = [('is_member', '=', True)]
        if mode == 'assigned':
            member_domain.append(('id', 'in', scope or [0]))
        people = Partner.search(member_domain)
        active = people.filtered(lambda p: p.membership_status in ACTIVE_STATUSES)

        year_start = today.replace(month=1, day=1)
        data = {
            'scope': 'church' if mode == 'all' else 'assigned',
            'membership': {
                'active_members': len(active),
                'visitors': len(people.filtered(lambda p: p.membership_status in (False, 'visitor'))),
                'new_this_year': len(active.filtered(
                    lambda p: p.member_join_date and p.member_join_date >= year_start)),
                'new_visitors_30d': len(people.filtered(
                    lambda p: p.membership_status in (False, 'visitor')
                    and p.create_date and p.create_date >= now - timedelta(days=30))),
                'inactive': len(people.filtered(lambda p: p.membership_status == 'inactive')),
            },
        }
        data['attendance'] = self._attendance(people, mode, today, now, weeks, active)
        data['groups'] = self._groups(people, mode, active)
        data['celebrations'] = self._celebrations(people, today)

        care = self.env['pastoral.care.note'].app_get_care_summary(employee.id)
        data['care'] = care.get('summary', {}) if care.get('success') else {}

        if employee.staff_role == 'admin' and 'church.give.transaction' in self.env:
            data['giving'] = self._giving(today)
        return {'success': True, 'dashboard': data}

    @api.model
    def app_get_absent_members(self, requester_staff_id=None, days=30):
        """Active members (in the caller's scope) with no check-in in the last
        `days` days — the list behind the dashboard's "Absent 30+ days" card.
        Longest-absent first; people never checked in come first of all."""
        Partner = self.env['res.partner'].sudo()
        mode, scope = Partner._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}

        domain = [('is_member', '=', True), ('membership_status', 'in', ACTIVE_STATUSES)]
        if mode == 'assigned':
            domain.append(('id', 'in', scope or [0]))
        active = Partner.search(domain)

        Attendance = self.env['church.event.attendance'].sudo()
        cutoff = fields.Datetime.now() - timedelta(days=days or 30)
        last_seen = {}
        for rec in Attendance.search([('member_id', 'in', active.ids or [0])],
                                     order='check_in_time desc'):
            last_seen.setdefault(rec.member_id.id, rec)

        absent = []
        for person in active:
            last = last_seen.get(person.id)
            if last and last.check_in_time >= cutoff:
                continue
            absent.append({
                'id': person.id,
                'name': person.name or '',
                'phone': person.phone or '',
                'member_number': person.member_number or '',
                'care_status': person.care_status or '',
                'write_date': fields.Datetime.to_string(person.write_date) if person.write_date else False,
                'last_check_in': fields.Datetime.to_string(last.check_in_time) if last else False,
                'last_service': last.event_id.name if last else '',
            })
        absent.sort(key=lambda a: (a['last_check_in'] or '', a['name']))
        return {'success': True, 'days': days or 30, 'members': absent}

    # ── Parts ───────────────────────────────────────────────────

    def _attendance(self, people, mode, today, now, weeks, active):
        Attendance = self.env['church.event.attendance'].sudo()
        week_start = today - timedelta(days=today.weekday())  # Monday
        first_week = week_start - timedelta(weeks=weeks - 1)
        domain = [('check_in_time', '>=', datetime.combine(first_week, time.min))]
        if mode == 'assigned':
            domain.append(('member_id', 'in', people.ids or [0]))
        records = Attendance.search(domain)

        per_week = defaultdict(set)
        for rec in records:
            day = fields.Datetime.context_timestamp(self, rec.check_in_time).date()
            monday = day - timedelta(days=day.weekday())
            per_week[monday].add(rec.member_id.id)
        trend = []
        for i in range(weeks):
            monday = first_week + timedelta(weeks=i)
            trend.append({'week': fields.Date.to_string(monday), 'people': len(per_week.get(monday, ()))})

        # Average over the last 4 complete weeks (the current week is partial).
        complete = [w['people'] for w in trend[:-1]][-4:]
        weekly_average = round(sum(complete) / len(complete)) if complete else 0

        last = Attendance.search(
            [('event_id.date_start', '<=', now)] +
            ([('member_id', 'in', people.ids or [0])] if mode == 'assigned' else []),
            order='check_in_time desc', limit=1)
        last_service = False
        if last:
            service = last.event_id
            count_domain = [('event_id', '=', service.id)]
            if mode == 'assigned':
                count_domain.append(('member_id', 'in', people.ids or [0]))
            last_service = {
                'name': service.name,
                'date_start': fields.Datetime.to_string(service.date_start),
                'people': Attendance.search_count(count_domain),
            }

        # "Not seen in 30 days" only means something once check-in is in use.
        not_seen = None
        if Attendance.search_count([]):
            seen = set(Attendance.search(
                [('check_in_time', '>=', now - timedelta(days=30))]).mapped('member_id').ids)
            not_seen = len([p for p in active if p.id not in seen])

        return {
            'trend': trend,
            'weekly_average': weekly_average,
            'this_week': trend[-1]['people'] if trend else 0,
            'last_service': last_service,
            'not_seen_30d': not_seen,
        }

    def _groups(self, people, mode, active):
        Group = self.env['cell.group'].sudo()
        groups = Group.search([]) if mode == 'all' else Group.search(
            ['|', ('leader_id', 'in', people.ids or [0]), ('member_ids', 'in', people.ids or [0])])
        in_groups = set(groups.mapped('member_ids').ids) | set(groups.mapped('leader_id').ids)
        return {
            'groups': len(groups),
            'members_in_groups': len([p for p in active if p.id in in_groups]),
            'members_without_group': len([p for p in active if p.id not in in_groups]),
        }

    def _celebrations(self, people, today, days=7):
        """Birthdays and wedding anniversaries in the next `days` days."""
        upcoming = []
        for person in people:
            for kind, date in (('birthday', person.date_of_birth),
                               ('anniversary', person.wedding_anniversary)):
                if not date:
                    continue
                try:
                    this_year = date.replace(year=today.year)
                except ValueError:  # 29 February in a non-leap year
                    this_year = date.replace(year=today.year, day=28)
                if this_year < today:
                    try:
                        this_year = this_year.replace(year=today.year + 1)
                    except ValueError:
                        this_year = this_year.replace(year=today.year + 1, day=28)
                in_days = (this_year - today).days
                if in_days <= days:
                    upcoming.append({
                        'member_id': person.id,
                        'name': person.name,
                        'type': kind,
                        'date': fields.Date.to_string(this_year),
                        'in_days': in_days,
                        'years': this_year.year - date.year,
                    })
        upcoming.sort(key=lambda c: (c['in_days'], c['name'] or ''))
        return upcoming[:20]

    def _giving(self, today):
        Tx = self.env['church.give.transaction'].sudo()
        month_start = today.replace(day=1)
        prev_start = (month_start - timedelta(days=1)).replace(day=1)

        def total(start, end):
            txs = Tx.search([
                ('state', '=', 'completed'),
                ('transaction_date', '>=', datetime.combine(start, time.min)),
                ('transaction_date', '<', datetime.combine(end, time.min)),
            ])
            return round(sum(txs.mapped('amount_pkr'))), len(txs)

        next_month = (month_start + timedelta(days=32)).replace(day=1)
        this_total, this_count = total(month_start, next_month)
        last_total, _ = total(prev_start, month_start)
        return {
            'this_month_pkr': this_total,
            'this_month_count': this_count,
            'last_month_pkr': last_total,
        }
