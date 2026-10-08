from odoo import api, fields, models
from .report_rules import validate, date_domain, jobs, member_filter, MAX_SELECTED_MEMBERS


class ChurchReportMobile(models.AbstractModel):
    _inherit = 'church.dashboard'

    def _report_admin(self, staff_id):
        if isinstance(staff_id, bool) or not isinstance(staff_id, int) or staff_id <= 0:
            return None
        employee = self.env['hr.employee'].sudo().browse(staff_id).exists()
        return employee if employee and employee.is_app_active and employee.staff_role == 'admin' else None

    def _report_source(self, job, opts, employee):
        timezone = employee.user_id.tz or self.env.user.tz or 'UTC'
        dated = lambda field, dt=True: date_domain(field, opts, timezone, dt)
        sources = {
            'members': ('res.partner', [('is_member', '=', True)]),
            'families': ('church.family', []), 'groups': ('cell.group', []),
            'assignments': ('pastor.assignment', []),
            'services': ('church.service', dated('date_start')),
            'attendance': ('church.event.attendance', dated('check_in_time')),
            'donations': ('church.give.transaction', [('state', '=', 'completed')] + dated('transaction_date')),
            'pledges': ('church.give.pledge', dated('start_date', False)),
            'prayers': ('prayer.request', dated('create_date')),
            'notes': ('pastoral.care.note', dated('date', False)),
            'visitors': ('res.partner', [('visitor_stage', '!=', False)] + dated('first_visit_date', False)),
        }
        model, domain = sources[job]
        domain = domain + member_filter(job, opts.get('member_ids'))
        return self.env[model].sudo().with_context(active_test=False), domain

    @api.model
    def app_report_manifest(self, requester_staff_id=None, options=None):
        employee = self._report_admin(requester_staff_id)
        if not employee:
            return {'success': False, 'error': 'Not authorized', 'code': 'denied'}
        try:
            opts = validate(options)
            selected = opts['sections']
            counts, unavailable = {}, []
            for section in selected:
                from .report_rules import JOBS
                for job in JOBS[section]:
                    try:
                        with self.env.cr.savepoint():
                            source, domain = self._report_source(job, opts, employee)
                            counts[job] = source.search_count(domain)
                    except Exception:
                        unavailable.append(job)
            result = {'success': True, 'schema': 1, 'generated_by': employee.name,
                'timezone': employee.user_id.tz or self.env.user.tz or 'UTC',
                'generated_at': fields.Datetime.to_string(fields.Datetime.now()),
                'counts': counts, 'jobs': jobs(opts), 'unavailable': unavailable,
                'summaries': {}}
            summaries = result['summaries']
            def aggregate(key, callback):
                try:
                    with self.env.cr.savepoint():
                        summaries[key] = callback()
                except Exception:
                    result['unavailable'].append(key)
            if 'membership' in selected:
                def membership():
                    source, domain = self._report_source('members', opts, employee)
                    joined = domain + date_domain('member_join_date', opts, datetime_field=False)
                    return {'by_status': [{'status': status or 'unknown', 'count': count}
                        for status, count in source._read_group(domain, ['membership_status'], ['__count'])],
                        'new_members': source.search_count(joined + [('member_join_date', '!=', False)])}
                aggregate('membership', membership)
            if 'giving' in selected:
                def giving():
                    # Donations have a project and a category (there is no fund field).
                    source, domain = self._report_source('donations', opts, employee)
                    return {'by_fund': [{'fund': project.name if project else 'General giving', 'total_pkr': amount}
                        for project, amount in source._read_group(domain, ['project_id'], ['amount_pkr:sum'])],
                        'by_category': [{'category': category.name if category else 'Uncategorized', 'total_pkr': amount}
                        for category, amount in source._read_group(domain, ['category_id'], ['amount_pkr:sum'])]}
                aggregate('giving', giving)
            if 'worship' in selected:
                def attendance():
                    source, domain = self._report_source('attendance', opts, employee)
                    return {'by_event': [{'event': event.name if event else 'Unknown event', 'attendance_count': count}
                        for event, count in source._read_group(domain, ['event_id'], ['__count'])]}
                aggregate('attendance', attendance)
            if 'care' in selected:
                def care():
                    source, domain = self._report_source('prayers', opts, employee)
                    return {'by_status': [{'status': status or 'unknown', 'count': count}
                        for status, count in source._read_group(domain, ['care_status'], ['__count'])]}
                aggregate('care', care)
            if opts['member_ids']:
                aggregate('member_summary', lambda: self._member_summary(opts, employee))
            return result
        except (ValueError, TypeError, OverflowError):
            return {'success': False, 'code': 'invalid', 'error': 'Choose valid report dates and sections.'}

    def _member_summary(self, opts, employee):
        """One compact row per chosen member: given, pledged/paid, services, prayers."""
        def totals(job, group_field, aggregate_spec):
            try:
                source, domain = self._report_source(job, opts, employee)
                return {rec.id: value for rec, value in source._read_group(domain, [group_field], [aggregate_spec]) if rec}
            except Exception:
                return {}
        given = totals('donations', 'partner_id', 'amount_pkr:sum')
        attended = totals('attendance', 'member_id', '__count')
        prayers = totals('prayers', 'partner_id', '__count')
        pledged, paid = {}, {}
        try:
            source, domain = self._report_source('pledges', opts, employee)
            for rec in source.search(domain):
                pledged[rec.member_id.id] = pledged.get(rec.member_id.id, 0) + (rec.pledge_amount or 0)
                paid[rec.member_id.id] = paid.get(rec.member_id.id, 0) + (rec.paid_amount or 0)
        except Exception:
            pass
        members = self.env['res.partner'].sudo().with_context(active_test=False).browse(opts['member_ids']).exists()
        return {'rows': [{
            'id': m.id, 'name': m.name or '', 'member_number': m.member_number or '',
            'given_pkr': given.get(m.id, 0), 'pledged': pledged.get(m.id, 0), 'paid': paid.get(m.id, 0),
            'attended': attended.get(m.id, 0), 'prayers': prayers.get(m.id, 0),
        } for m in members.sorted(lambda p: (p.name or '').lower())]}

    @api.model
    def app_report_member_search(self, requester_staff_id=None, query='', family_id=None, limit=40):
        """Member picker for the report: search by name / member no. / phone,
        or every member of one family."""
        employee = self._report_admin(requester_staff_id)
        if not employee:
            return {'success': False, 'code': 'denied', 'error': 'Not authorized'}
        Partner = self.env['res.partner'].sudo()
        domain = [('is_member', '=', True)]
        if family_id:
            domain.append(('family_id', '=', int(family_id)))
        query = (query or '').strip()
        if query:
            domain += ['|', '|', ('name', 'ilike', query), ('member_number', 'ilike', query), ('phone', 'ilike', query)]
        limit = max(1, min(int(limit or 40), 200 if family_id else 100))
        rows = Partner.search(domain, order='name', limit=limit)
        return {'success': True, 'max_selected': MAX_SELECTED_MEMBERS, 'members': [{
            'id': p.id, 'name': p.name or '', 'member_number': p.member_number or '',
            'phone': p.phone or '', 'family_id': p.family_id.id or 0, 'family': p.family_id.name or '',
        } for p in rows]}

    @api.model
    def app_report_page(self, requester_staff_id=None, options=None, section=None, after_id=0, limit=100):
        employee = self._report_admin(requester_staff_id)
        if not employee:
            return {'success': False, 'code': 'denied', 'error': 'Not authorized'}
        try:
            opts = validate(options)
            if section not in jobs(opts):
                return {'success': False, 'code': 'denied', 'error': 'Section not selected or private details excluded'}
            if isinstance(after_id, bool) or not isinstance(after_id, int) or after_id < 0:
                raise ValueError('Invalid cursor')
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
                raise ValueError('Invalid page size')
            source, domain = self._report_source(section, opts, employee)
            records = source.search(domain + [('id', '>', after_id)], order='id asc', limit=limit + 1)
            more = len(records) > limit
            records = records[:limit]
            rows = [self._report_row(section, record, requester_staff_id, opts) for record in records]
            return {'success': True, 'rows': rows, 'has_more': more,
                    'next_id': records[-1].id if records else after_id}
        except (ValueError, TypeError, OverflowError):
            return {'success': False, 'code': 'invalid', 'error': 'Invalid report page request'}

    def _report_row(self, section, rec, staff_id, opts):
        if section == 'members':
            detail = rec.app_get_member_detail(rec.id, requester_staff_id=staff_id)
            if not detail.get('success'):
                raise ValueError('Member profile could not be loaded')
            row = dict(detail['member'])
            if not opts['sensitive']:
                row.pop('care_status', None)
                row.pop('care_status_date', None)
            return row
        if section == 'families':
            return {'id': rec.id, 'name': rec.name, 'head_name': rec.head_id.name or '', 'member_count': rec.member_count}
        if section == 'groups':
            return rec.read(['name', 'zone', 'leader_id', 'member_count', 'meeting_day', 'meeting_time'])[0]
        if section == 'assignments':
            return {'id': rec.id, 'member_name': rec.member_id.name, 'pastor_name': rec.pastor_id.name}
        if section == 'services':
            return rec.read(['name', 'date_start', 'location'])[0]
        if section == 'attendance':
            return {'id': rec.id, 'event': rec.event_id.name, 'member_name': rec.member_id.name,
                    'check_in_time': fields.Datetime.to_string(rec.check_in_time), 'method': rec.method}
        if section == 'donations':
            return {'id': rec.id, 'date': fields.Datetime.to_string(rec.transaction_date),
                'donor': 'Anonymous' if rec.is_anonymous else rec.donor_name,
                'fund': rec.project_id.name or rec.project_name or rec.category_id.name or 'General giving',
                'amount': rec.amount, 'currency': rec.currency, 'gateway': rec.gateway}
        if section == 'pledges':
            return rec._read_pledges(rec)[0]
        if section == 'prayers':
            row = rec.read(['subject', 'message', 'create_date', 'visibility', 'urgency', 'care_status', 'response', 'testimony'])[0]
            row['member_name'] = rec.partner_id.name or ''
            return row
        if section == 'notes':
            row = rec.read(['date', 'note_type', 'content', 'outcome', 'follow_up_date', 'follow_up_done'])[0]
            row['member_name'] = rec.member_id.name
            return row
        if section == 'visitors':
            return rec._visitor_dict()
