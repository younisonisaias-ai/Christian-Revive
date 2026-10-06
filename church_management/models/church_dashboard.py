from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import models, fields, api

# Membership statuses that count as "active members" on the dashboard.
ACTIVE_STATUSES = ('new_convert', 'member', 'worker', 'leader')

CARE_STATUS_LABELS = {
    'healthy': 'Doing Well',
    'new_member': 'New Member',
    'needs_follow_up': 'Needs Follow-Up',
    'prayer_needed': 'Prayer Needed',
    'hospitalized': 'Hospitalized',
    'bereavement': 'Bereavement',
    'counseling': 'Counseling',
    'at_risk': 'At Risk',
    'inactive': 'Inactive',
}

CARE_STATUS_COLORS = {
    'healthy': '#10b981',
    'new_member': '#38bdf8',
    'needs_follow_up': '#f59e0b',
    'prayer_needed': '#6366f1',
    'hospitalized': '#ef4444',
    'bereavement': '#8b5cf6',
    'counseling': '#06b6d4',
    'at_risk': '#dc2626',
    'inactive': '#94a3b8',
}

SERVICE_TYPE_LABELS = {
    'sabbath_worship': 'Sabbath Worship',
    'sabbath_school': 'Sabbath School',
    'prayer_meeting': 'Prayer Meeting',
    'bible_study': 'Bible Study',
    'youth': 'Youth Ministry',
    'children': 'Children Ministry',
    'small_group': 'Small Group',
    'special_event': 'Special Event',
    'other': 'Other',
}


class ChurchDashboard(models.AbstractModel):
    """Numbers and analytics for the Church Management dashboard in both the app
    and the Odoo backend Admin Dashboard.
    """
    _name = 'church.dashboard'
    _description = 'Church Management Dashboard'

    @api.model
    def get_admin_dashboard_data(self, period='all'):
        """Comprehensive bird's-eye view data for the backend Admin Dashboard."""
        Partner = self.env['res.partner'].sudo()
        Attendance = self.env['church.event.attendance'].sudo()
        Service = self.env['church.service'].sudo()
        Group = self.env['cell.group'].sudo()
        Family = self.env['church.family'].sudo()
        Note = self.env['pastoral.care.note'].sudo()
        Prayer = self.env['prayer.request'].sudo() if 'prayer.request' in self.env else None
        Employee = self.env['hr.employee'].sudo()

        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        year_start = today.replace(month=1, day=1)
        month_start = today.replace(day=1)
        cutoff_30d = now - timedelta(days=30)
        cutoff_7d = now - timedelta(days=7)

        # ── 1. Membership Metrics ───────────────────────────────────
        all_members = Partner.search([('is_member', '=', True)])
        active_members = all_members.filtered(lambda p: p.membership_status in ACTIVE_STATUSES)
        
        status_counts = {
            'leader': len(all_members.filtered(lambda p: p.membership_status == 'leader')),
            'worker': len(all_members.filtered(lambda p: p.membership_status == 'worker')),
            'member': len(all_members.filtered(lambda p: p.membership_status == 'member')),
            'new_convert': len(all_members.filtered(lambda p: p.membership_status == 'new_convert')),
            'inactive': len(all_members.filtered(lambda p: p.membership_status == 'inactive')),
            'transferred': len(all_members.filtered(lambda p: p.membership_status == 'transferred')),
            'deceased': len(all_members.filtered(lambda p: p.membership_status == 'deceased')),
        }
        
        visitors_count = Partner.search_count([
            '|', ('visitor_stage', '!=', False), ('membership_status', '=', 'visitor')
        ])
        new_visitors_30d = Partner.search_count([
            '|', ('visitor_stage', '!=', False), ('membership_status', '=', 'visitor'),
            ('create_date', '>=', cutoff_30d)
        ])
        
        relatives_to_verify = Partner.search_count([('family_verified', '=', False)])
        total_families = Family.search_count([])

        new_this_year = len(active_members.filtered(
            lambda p: p.member_join_date and p.member_join_date >= year_start
        ))
        new_this_month = len(active_members.filtered(
            lambda p: p.member_join_date and p.member_join_date >= month_start
        ))

        avg_completeness = 0
        if active_members:
            avg_completeness = round(sum(active_members.mapped('profile_completeness')) / len(active_members))

        # ── 2. Cell Groups Metrics ──────────────────────────────────
        groups = Group.search([])
        in_groups = set(groups.mapped('member_ids').ids) | set(groups.mapped('leader_id').ids)
        active_in_groups = len([p for p in active_members if p.id in in_groups])
        active_without_group = len(active_members) - active_in_groups
        group_coverage_pct = round((active_in_groups / len(active_members) * 100)) if active_members else 0

        # ── 3. Pastoral Care & Health Metrics ───────────────────────
        care_status_counts = {}
        for code, label in CARE_STATUS_LABELS.items():
            care_status_counts[code] = {
                'code': code,
                'label': label,
                'color': CARE_STATUS_COLORS.get(code, '#64748b'),
                'count': len(active_members.filtered(lambda p: p.care_status == code)),
            }
        
        urgent_care_members = active_members.filtered(
            lambda p: p.care_status in ('at_risk', 'hospitalized', 'bereavement')
        )
        needs_attention_count = len(active_members.filtered(
            lambda p: p.care_status in ('needs_follow_up', 'at_risk', 'hospitalized', 'bereavement', 'counseling', 'prayer_needed')
        ))

        total_care_notes = Note.search_count([])
        pending_follow_ups = Note.search_count([
            ('follow_up_done', '=', False),
            ('follow_up_date', '!=', False),
            ('follow_up_date', '<=', today + timedelta(days=7))
        ])

        # ── 4. Attendance & Services Metrics ────────────────────────
        attendance_overview = self._attendance(all_members, 'all', today, now, 8, active_members)
        total_services = Service.search_count([])
        services_this_month = Service.search_count([
            ('date_start', '>=', datetime.combine(month_start, time.min))
        ])
        total_checkins = Attendance.search_count([])
        checkins_this_month = Attendance.search_count([
            ('check_in_time', '>=', datetime.combine(month_start, time.min))
        ])

        service_types_chart = []
        for stype_code, stype_name in SERVICE_TYPE_LABELS.items():
            s_count = Service.search_count([('service_type', '=', stype_code)])
            att_count = Attendance.search_count([('event_id.service_type', '=', stype_code)])
            if s_count > 0 or att_count > 0:
                service_types_chart.append({
                    'type': stype_code,
                    'label': stype_name,
                    'services': s_count,
                    'attendance': att_count,
                })
        service_types_chart.sort(key=lambda s: s['attendance'], reverse=True)

        # ── 5. Prayer Requests Metrics ──────────────────────────────
        prayer_metrics = {
            'total': 0,
            'open': 0,
            'urgent': 0,
            'unassigned': 0,
            'answered': 0,
        }
        recent_prayers = []
        if Prayer:
            open_domain = [('care_status', 'in', ('submitted', 'assigned', 'praying', 'follow_up'))]
            prayer_metrics['total'] = Prayer.search_count([])
            prayer_metrics['open'] = Prayer.search_count(open_domain)
            prayer_metrics['urgent'] = Prayer.search_count(open_domain + [('urgency', 'in', ('urgent', 'high'))])
            prayer_metrics['unassigned'] = Prayer.search_count(open_domain + [('assigned_pastor_id', '=', False)])
            prayer_metrics['answered'] = Prayer.search_count([('care_status', '=', 'answered')])

            for p in Prayer.search(open_domain, order='create_date desc', limit=6):
                recent_prayers.append({
                    'id': p.id,
                    'name': p.name or p.requester_display_name or 'Anonymous',
                    'subject': p.subject or 'Prayer Request',
                    'category': p.category or '',
                    'urgency': p.urgency or 'normal',
                    'care_status': p.care_status or 'submitted',
                    'pastor_name': p.assigned_pastor_id.name if p.assigned_pastor_id else 'Unassigned',
                    'date': fields.Datetime.to_string(p.create_date) if p.create_date else '',
                })

        # ── 6. Pastoral Staff & Assignments ─────────────────────────
        pastors = Employee.search([('staff_role', '=', 'pastor')])
        assigned_partners_ids = set()
        for pastor in pastors:
            assigned_partners_ids.update(pastor.assigned_member_ids.ids)
        
        pastor_stats = {
            'total_pastors': len(pastors),
            'senior_pastors': len(pastors.filtered(lambda e: e.is_senior_pastor)),
            'assigned_members': len(assigned_partners_ids & set(active_members.ids)),
            'unassigned_members': len(active_members) - len(assigned_partners_ids & set(active_members.ids)),
        }

        # ── 7. Action Tables (Urgent alerts, Absent, Celebrations, etc.) ─
        urgent_alerts_list = []
        for person in urgent_care_members[:8]:
            last_note = Note.search([('member_id', '=', person.id)], order='date desc', limit=1)
            urgent_alerts_list.append({
                'id': person.id,
                'name': person.name,
                'phone': person.phone or 'No phone',
                'member_number': person.member_number or '-',
                'care_status': person.care_status,
                'care_status_label': CARE_STATUS_LABELS.get(person.care_status, person.care_status),
                'status_color': CARE_STATUS_COLORS.get(person.care_status, '#dc2626'),
                'last_note': last_note.content[:60] + '...' if last_note and last_note.content else 'No note recorded',
                'last_note_date': fields.Date.to_string(last_note.date) if last_note else '',
            })

        absent_data = self.app_get_absent_members(requester_staff_id=None, days=30)
        absent_members_list = absent_data.get('members', [])[:10] if absent_data.get('success') else []

        celebrations = self._celebrations(all_members, today, days=14)

        recent_services = []
        for s in Service.search([], order='date_start desc', limit=5):
            recent_services.append({
                'id': s.id,
                'name': s.name,
                'service_type': s.service_type,
                'type_label': SERVICE_TYPE_LABELS.get(s.service_type, s.service_type or ''),
                'date_start': fields.Datetime.to_string(s.date_start) if s.date_start else '',
                'attendance_count': s.attendance_count,
                'rsvp_expected': s.rsvp_expected or 0,
                'location': s.location or '',
                'is_active': s.is_active,
            })

        cell_groups_summary = []
        for g in groups[:6]:
            cell_groups_summary.append({
                'id': g.id,
                'name': g.name,
                'leader_name': g.leader_id.name if g.leader_id else 'Unassigned',
                'member_count': g.member_count,
                'meeting_day': g.meeting_day.title() if g.meeting_day else 'TBD',
                'meeting_time': g.meeting_time or '',
                'zone': g.zone or '',
            })

        giving_data = {}
        if 'church.give.transaction' in self.env:
            giving_data = self._giving(today)

        status_distribution_chart = [
            {'label': 'Regular Members', 'count': status_counts['member'], 'color': '#3b82f6'},
            {'label': 'Workers & Volunteers', 'count': status_counts['worker'], 'color': '#10b981'},
            {'label': 'Leaders & Pastors', 'count': status_counts['leader'], 'color': '#8b5cf6'},
            {'label': 'New Converts', 'count': status_counts['new_convert'], 'color': '#f59e0b'},
            {'label': 'Visitors', 'count': visitors_count, 'color': '#06b6d4'},
            {'label': 'Inactive', 'count': status_counts['inactive'], 'color': '#94a3b8'},
        ]

        care_chart_data = [
            {'label': v['label'], 'count': v['count'], 'color': v['color']}
            for v in care_status_counts.values() if v['count'] > 0
        ]

        return {
            'success': True,
            'today_formatted': today.strftime('%A, %d %B %Y'),
            'viewer': {
                'name': self.env.user.name,
                'is_admin': self.env.user.has_group('church_management.group_church_admin') or self.env.user.has_group('base.group_system'),
            },
            'kpi': {
                'active_members': len(active_members),
                'total_members': len(all_members),
                'status_counts': status_counts,
                'new_this_year': new_this_year,
                'new_this_month': new_this_month,
                'total_visitors': visitors_count,
                'new_visitors_30d': new_visitors_30d,
                'relatives_to_verify': relatives_to_verify,
                'total_families': total_families,
                'avg_completeness': avg_completeness,
                'total_services': total_services,
                'services_this_month': services_this_month,
                'total_checkins': total_checkins,
                'checkins_this_month': checkins_this_month,
                'weekly_avg_attendance': attendance_overview.get('weekly_average', 0),
                'this_week_attendance': attendance_overview.get('this_week', 0),
                'absent_30d_count': attendance_overview.get('not_seen_30d') or len(absent_members_list),
                'cell_groups_count': len(groups),
                'members_in_groups': active_in_groups,
                'members_without_group': active_without_group,
                'group_coverage_pct': group_coverage_pct,
                'urgent_care_count': len(urgent_care_members),
                'needs_attention_count': needs_attention_count,
                'total_care_notes': total_care_notes,
                'pending_follow_ups': pending_follow_ups,
                'prayers': prayer_metrics,
                'pastor_stats': pastor_stats,
                'giving': giving_data,
            },
            'charts': {
                'attendance_trend': attendance_overview.get('trend', []),
                'status_distribution': status_distribution_chart,
                'care_distribution': care_chart_data,
                'service_types': service_types_chart,
            },
            'tables': {
                'urgent_alerts': urgent_alerts_list,
                'absent_members': absent_members_list,
                'celebrations': celebrations,
                'recent_services': recent_services,
                'recent_prayers': recent_prayers,
                'cell_groups': cell_groups_summary,
            },
        }

    # ── Original Mobile App Methods (preserved) ─────────────────
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
            'viewer': {
                'name': employee.name or '',
                'role': employee.staff_role or '',
                'is_senior_pastor': bool(employee.is_senior_pastor),
                'can_assign_pastors': mode == 'all',
                'can_manage_funds': employee.staff_role in ('admin', 'finance_officer'),
            },
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
        if requester_staff_id:
            mode, scope = Partner._church_caller_scope(requester_staff_id=requester_staff_id)
            if mode not in ('all', 'assigned'):
                return {'success': False, 'error': 'Not authorized'}
        else:
            mode, scope = 'all', []

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
                'care_status_label': CARE_STATUS_LABELS.get(person.care_status, person.care_status or ''),
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
            formatted_label = monday.strftime('%d %b')
            trend.append({
                'week': fields.Date.to_string(monday),
                'label': formatted_label,
                'people': len(per_week.get(monday, ()))
            })

        complete = [w['people'] for w in trend[:-1]][-4:]
        weekly_average = round(sum(complete) / len(complete)) if complete else (trend[-1]['people'] if trend else 0)

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

        not_seen = 0
        if Attendance.search_count([]):
            seen = set(Attendance.search(
                [('check_in_time', '>=', now - timedelta(days=30))]).mapped('member_id').ids)
            not_seen = len([p for p in active if p.id not in seen])
        else:
            not_seen = len(active)

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

    def _celebrations(self, people, today, days=14):
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
                        'phone': person.phone or '',
                        'type': kind,
                        'type_label': '🎂 Birthday' if kind == 'birthday' else '💍 Anniversary',
                        'date': fields.Date.to_string(this_year),
                        'date_formatted': this_year.strftime('%d %b'),
                        'in_days': in_days,
                        'days_label': 'Today' if in_days == 0 else ('Tomorrow' if in_days == 1 else f'in {in_days} days'),
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
