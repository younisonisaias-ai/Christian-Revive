from collections import defaultdict
from datetime import timedelta
import re
from psycopg2 import IntegrityError
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression
from .models import audit
from .rules import positive_id, money, page_args, request_key, request_hash, contact_keys, KINDS, STAGES


class ChurchOperations(models.AbstractModel):
    _name = 'church.operations'
    _description = 'Scoped church operations API'

    def _staff(self, staff_id):
        positive_id(staff_id)
        staff = self.env['hr.employee'].sudo().browse(staff_id).exists()
        if not staff or not staff.active or not staff.is_app_active:
            raise AccessError('Church staff access is not enabled.')
        if staff.staff_role not in ('admin', 'pastor', 'finance_officer', 'church_volunteer') and not staff.church_operations_volunteer:
            raise AccessError('Your role does not have access to church operations.')
        return staff

    def _mode(self, staff):
        if staff.staff_role == 'admin' or (staff.staff_role == 'pastor' and staff.is_senior_pastor):
            return 'all'
        return 'assigned' if staff.staff_role == 'pastor' else 'finance' if staff.staff_role == 'finance_officer' else 'volunteer'

    def _people_domain(self, staff):
        mode = self._mode(staff)
        if mode == 'all':
            return []
        if mode == 'finance':
            return [('id', '=', 0)]
        owned = [('church_visitor_owner_id', '=', staff.id)]
        if mode == 'volunteer':
            return owned
        ids = self.env['pastor.assignment'].sudo().search([('pastor_id', '=', staff.id)]).mapped('member_id').ids
        # Relatives an assigned member added from the app share that member's
        # pastor, so the pastor can find and verify them.
        relatives = [('added_by_partner_id', 'in', ids)] if ids else [('id', '=', 0)]
        return expression.OR([[('id', 'in', ids)], relatives, owned, [('visitor_added_by_id', '=', staff.id)]])

    def _member(self, staff, member_id):
        positive_id(member_id)
        rec = self.env['res.partner'].sudo().search(expression.AND([
            [('id', '=', member_id)], self._people_domain(staff),
            expression.OR([[('is_member', '=', True)], [('visitor_stage', '!=', False)]])]), limit=1)
        if not rec:
            raise AccessError('This person is outside your church assignment.')
        return rec

    def _finance(self, staff):
        if staff.staff_role not in ('admin', 'finance_officer'):
            raise AccessError('Finance access is required for this action.')

    def _people(self, staff):
        if staff.staff_role not in ('admin', 'pastor'):
            raise AccessError('Pastor or Admin access is required.')

    def _task_domain(self, staff):
        mode = self._mode(staff)
        if mode == 'all':
            return []
        if mode == 'finance':
            return [('kind', '=', 'pledge'), ('assigned_to_id', '=', staff.id)]
        people = self.env['res.partner'].sudo().search(self._people_domain(staff)).ids
        if mode == 'volunteer':
            return [('kind', '=', 'visitor'), ('assigned_to_id', '=', staff.id), ('member_id', 'in', people)]
        return expression.OR([[('member_id', 'in', people)],
            [('member_id', '=', False), ('assigned_to_id', '=', staff.id)]])

    def _page(self, model, domain, payload, serializer):
        after, limit = page_args(payload)
        descending = payload.get('descending') is True
        cursor = [('id', '<' if descending else '>', after)] if after else []
        rows = model.search(domain + cursor, order='id desc' if descending else 'id', limit=limit + 1)
        return {'rows': [serializer(v) for v in rows[:limit]], 'has_more': len(rows) > limit,
                'next_id': rows[:limit][-1].id if rows[:limit] else after}

    @api.model
    def app_church_operations(self, requester_staff_id=None, action='', payload=None):
        actions = {
            'home': self._home, 'choices': self._choices, 'directory': self._directory,
            'create_member': self._create_member, 'tasks': self._tasks,
            'save_task': self._save_task, 'complete_task': self._complete_task,
            'update_task': self._update_task,
            'visitors': self._visitors, 'contact': self._contact, 'contacts': self._contacts,
            'timeline': self._timeline, 'attendance': self._attendance,
            'finance': self._finance_list, 'reconcile': self._reconcile,
            'refund': self._refund, 'receipt': self._receipt, 'audit': self._audit_list,
            'pledges': self._pledges, 'reminders': self._reminders,
        }
        mutations = {'create_member', 'save_task', 'complete_task', 'update_task', 'contact', 'reconcile', 'refund'}
        try:
            staff = self._staff(requester_staff_id)
            if action not in actions or not isinstance(payload or {}, dict):
                raise ValueError('Unknown church operation.')
            data = dict(payload or {})
            with self.env.cr.savepoint():
                target = self.with_context(church_ops_actor=staff.id)
                handler = getattr(target, actions[action].__name__)
                if action in mutations:
                    # Recheck targets before replaying a prior result: assignments
                    # and roles can change between retries on different devices.
                    if action in ('refund', 'reconcile'):
                        self._tx(staff, data.get('transaction_id'))
                        if action == 'refund' and staff.staff_role != 'admin':
                            raise AccessError('An Admin must record refunds.')
                    if action == 'create_member': self._people(staff)
                    if action in ('contact', 'save_task') and data.get('member_id'):
                        self._member(staff, data['member_id'])
                    if action in ('complete_task', 'update_task'):
                        permitted = self.env['church.ops.task'].sudo().search(self._task_domain(staff) + [
                            ('id', '=', positive_id(data.get('task_id')))], limit=1)
                        if not permitted or (permitted.assigned_to_id != staff and staff.staff_role != 'admin'):
                            raise AccessError('This task is no longer assigned to you.')
                    key, fingerprint = request_key(data), request_hash(action, data)
                    ledger = self.env['church.ops.request'].sudo()
                    previous = ledger.search([('staff_id', '=', staff.id), ('key', '=', key)], limit=1)
                    if previous:
                        if previous.fingerprint != fingerprint:
                            raise ValueError('This save identifier belongs to different form data.')
                        if not previous.result:
                            raise ValueError('This save is still processing. Please retry.')
                        return dict(previous.result)
                    entry = ledger.create({'staff_id': staff.id, 'key': key, 'fingerprint': fingerprint})
                    result = {'success': True, **handler(staff, data)}
                    entry.write({'result': result})
                    return result
                return {'success': True, **handler(staff, data)}
        except AccessError as exc:
            return {'success': False, 'code': 'denied', 'error': str(exc)}
        except (ValueError, ValidationError, TypeError, KeyError) as exc:
            return {'success': False, 'code': 'invalid', 'error': str(exc) or 'Check the form and retry.'}
        except IntegrityError:
            return {'success': False, 'code': 'retry', 'error': 'This save is already processing. Retry to confirm the result.'}

    def _today(self, staff):
        # One local "today" so the home counts and the lists always agree.
        return fields.Date.context_today(self.with_context(tz=staff.user_id.tz or 'UTC'))

    def _home(self, staff, data):
        today = self._today(staff)
        tasks = self.env['church.ops.task'].sudo()
        domain = self._task_domain(staff) + [('state', '=', 'open')]
        counts = {'tasks': tasks.search_count(domain),
                  'overdue': tasks.search_count(domain + [('due_date', '<', today)])}
        if staff.staff_role in ('admin', 'pastor'):
            partner = self.env['res.partner'].sudo()
            scope = self._people_domain(staff)
            counts['verification'] = partner.search_count(scope + [('is_member', '=', True),
                ('family_verified', '=', False), ('added_by_partner_id', '!=', False)])
            counts['visitors'] = partner.search_count(scope + [('visitor_stage', '=', 'new')])
        if staff.staff_role in ('admin', 'finance_officer'):
            counts['unverified_gifts'] = self.env['church.give.transaction'].sudo().search_count([
                ('state', '=', 'completed'), ('church_reconciled', '=', False)])
            counts['overdue_pledges'] = self.env['church.give.pledge'].sudo().search_count([('status', '=', 'overdue')])
        return {'counts': counts, 'staff_name': staff.name, 'staff_id': staff.id,
            'people': staff.staff_role in ('admin', 'pastor'),
            'finance': staff.staff_role in ('admin', 'finance_officer'),
            'admin': staff.staff_role == 'admin', 'volunteer': self._mode(staff) == 'volunteer'}

    def _choices(self, staff, data):
        kind, query = data.get('kind'), (data.get('query') or '').strip()[:100]
        partner = self.env['res.partner'].sudo()
        scope = self._people_domain(staff)
        if kind == 'member':
            self._people(staff)
            model, domain = partner, scope + [('is_member', '=', True)]
        elif kind in ('family', 'group'):
            self._people(staff)
            people = partner.search(scope).ids if self._mode(staff) != 'all' else None
            model = self.env['church.family' if kind == 'family' else 'cell.group'].sudo()
            domain = [('member_ids', 'in', people)] if people is not None else []
        elif kind == 'pastor':
            self._people(staff)
            model = self.env['hr.employee'].sudo()
            domain = [('staff_role', '=', 'pastor'), ('active', '=', True), ('is_app_active', '=', True)]
            if self._mode(staff) != 'all': domain.append(('id', '=', staff.id))
        elif kind == 'staff':
            if self._mode(staff) not in ('all', 'assigned'):
                raise AccessError('You cannot reassign church work.')
            model = self.env['hr.employee'].sudo()
            domain = [('active', '=', True), ('is_app_active', '=', True)] + expression.OR([
                [('staff_role', 'in', ['admin', 'pastor', 'finance_officer', 'church_volunteer'])], [('church_operations_volunteer', '=', True)]])
        else:
            raise ValueError('Choose a directory filter.')
        if query: domain.append(('name', 'ilike', query))
        return self._page(model, domain, data, lambda r: {'id': r.id, 'name': r.name})

    def _directory(self, staff, data):
        self._people(staff)
        domain = self._people_domain(staff) + [('is_member', '=', True)]
        if data.get('status'): domain.append(('membership_status', '=', data['status']))
        if data.get('verification'): domain += [('family_verified', '=', False), ('added_by_partner_id', '!=', False)]
        for key, field in [('family_id', 'family_id'), ('group_id', 'cell_group_ids')]:
            if data.get(key):
                value = positive_id(data[key])
                if key == 'group_id':
                    ids = self.env['cell.group'].sudo().browse(value).exists().member_ids.ids
                    domain.append(('id', 'in', ids))
                else: domain.append((field, '=', value))
        if data.get('pastor_id'):
            ids = self.env['pastor.assignment'].sudo().search([('pastor_id', '=', positive_id(data['pastor_id']))]).mapped('member_id').ids
            domain.append(('id', 'in', ids))
        query = (data.get('query') or '').strip()[:100]
        if query:
            domain = expression.AND([domain, expression.OR([[(field, 'ilike', query)] for field in ('name', 'member_number', 'phone', 'email')])])
        return self._page(self.env['res.partner'].sudo(), domain, data, lambda r: {
            'id': r.id, 'name': r.name, 'status': r.membership_status or '',
            'number': r.member_number or '', 'family': r.family_id.name or '',
            'phone': r.phone or '', 'verified': r.family_verified})

    def _create_member(self, staff, data):
        self._people(staff)
        name, email, phone = str(data.get('name') or '').strip(), str(data.get('email') or '').strip(), str(data.get('phone') or '').strip()
        if not name: raise ValueError('Enter the member name.')
        keys = contact_keys(name, email, phone)
        duplicate_domain = expression.OR([[(field, '=', key)] for field, key in
            zip(('church_name_key', 'church_email_key', 'church_phone_key'), keys) if key])
        candidates = self.env['res.partner'].sudo().search(
            expression.AND([expression.OR([[('is_member', '=', True)], [('visitor_stage', '!=', False)]]), duplicate_domain]), limit=6)
        if candidates and data.get('confirm_duplicate') is not True:
            visible = candidates.filtered_domain(self._people_domain(staff))
            return {'duplicate': True, 'candidates': [{'id': r.id, 'name': r.name} for r in visible],
                    'message': 'Possible matching records exist. Review before creating a separate person.'}
        result = self.env['res.partner'].with_context(church_ops_actor=staff.id).app_create_member(
            {'name': name, 'phone': phone, 'email': email}, requester_staff_id=staff.id)
        if result.get('success') is not True: raise ValueError(result.get('error', 'Could not add member.'))
        audit(self.env, 'res.partner', result['member_id'], result['member_id'], 'Member created', ('name', 'phone', 'email'))
        return {'member_id': result['member_id']}

    def _task_row(self, rec):
        return {'id': rec.id, 'name': rec.name, 'member_id': rec.member_id.id or None,
            'member_name': rec.member_id.name or '', 'owner_id': rec.assigned_to_id.id,
            'owner': rec.assigned_to_id.name, 'due_date': str(rec.due_date), 'kind': rec.kind, 'state': rec.state}

    def _reminders(self, staff, data):
        domain = self._task_domain(staff) + [('assigned_to_id', '=', staff.id), ('state', '=', 'open')]
        records = self.env['church.ops.task'].sudo().search(domain, order='due_date, id', limit=40)
        return {'rows': [{'id': r.id, 'due_date': str(r.due_date)} for r in records]}

    def _pledges(self, staff, data):
        self._finance(staff)
        domain = [('status', '=', data['status'])] if data.get('status') else []
        return self._page(self.env['church.give.pledge'].sudo(), domain, data, lambda r: {
            'id': r.id, 'name': r.member_id.name, 'date': str(r.start_date),
            'detail': '%s %.2f pledged / %.2f confirmed paid%s' % (r.currency, r.pledge_amount,
                r.paid_amount, ' - Currency credit needs review' if r.church_balance_review else ''),
            'state': r.status})

    def _tasks(self, staff, data):
        domain = self._task_domain(staff) + [('state', '=', data.get('state', 'open'))]
        if data.get('only_mine'): domain.append(('assigned_to_id', '=', staff.id))
        if data.get('overdue'): domain.append(('due_date', '<', self._today(staff)))
        if data.get('member_id'):
            domain.append(('member_id', '=', self._member(staff, data['member_id']).id))
        result = self._page(self.env['church.ops.task'].sudo(), domain, data, self._task_row)
        return result

    def _save_task(self, staff, data):
        kind = data.get('kind', 'follow_up')
        if kind not in KINDS: raise ValueError('Choose a task type.')
        member = self._member(staff, data['member_id']) if data.get('member_id') else None
        owner = self._staff(data.get('owner_id') or staff.id)
        mode = self._mode(staff)
        if mode == 'volunteer' and (kind != 'visitor' or not member or owner != staff):
            raise AccessError('Volunteers may manage their own visitor tasks only.')
        if mode == 'finance' and (kind != 'pledge' or member or owner != staff):
            raise AccessError('Finance staff may create their own financial work items only.')
        if owner != staff and staff.staff_role not in ('admin', 'pastor'):
            raise AccessError('You cannot assign work to another person.')
        if member:
            self._member(owner, member.id)
        if self._mode(owner) == 'finance' and kind != 'pledge':
            raise ValueError('Finance staff can be assigned financial tasks only.')
        if self._mode(owner) == 'volunteer' and (kind != 'visitor' or not member or not member.visitor_stage):
            raise ValueError('Volunteers can be assigned visitor follow-ups only.')
        name = str(data.get('name') or '').strip()[:180]
        due = fields.Date.to_date(data.get('due_date'))
        if not name or not due: raise ValueError('A task title and due date are required.')
        task = self.env['church.ops.task'].sudo().create({'name': name, 'kind': kind,
            'member_id': member.id if member else False, 'assigned_to_id': owner.id,
            'created_by_id': staff.id, 'due_date': due})
        audit(self.env, task._name, task.id, member.id if member else None, 'Task created')
        return {'task': self._task_row(task)}

    def _complete_task(self, staff, data):
        task = self.env['church.ops.task'].sudo().search(self._task_domain(staff) + [('id', '=', positive_id(data.get('task_id')))], limit=1)
        if not task: raise AccessError('Task not available in your assignment.')
        if task.assigned_to_id != staff and staff.staff_role != 'admin':
            raise AccessError('Only its owner or an Admin may complete this task.')
        if task.state != 'open': raise ValueError('This task is already closed. Refresh your task list.')
        outcome = str(data.get('outcome') or '').strip()
        if not outcome: raise ValueError('Record the outcome before completing the task.')
        task.with_context(church_ops_actor=staff.id).write({'state': 'done', 'outcome': outcome, 'completed_at': fields.Datetime.now()})
        return {'task': self._task_row(task)}

    def _update_task(self, staff, data):
        task = self.env['church.ops.task'].sudo().search(self._task_domain(staff) + [
            ('id', '=', positive_id(data.get('task_id')))], limit=1)
        if not task or (task.assigned_to_id != staff and staff.staff_role != 'admin'):
            raise AccessError('Only the owner or an Admin may change this task.')
        if task.state != 'open': raise ValueError('Only open tasks can be changed.')
        due = fields.Date.to_date(data.get('due_date'))
        if not due: raise ValueError('Choose a due date.')
        owner = self._staff(data['owner_id']) if data.get('owner_id') else task.assigned_to_id
        if owner != task.assigned_to_id:
            if staff.staff_role not in ('admin', 'pastor'): raise AccessError('You cannot reassign this task.')
            if task.member_id: self._member(owner, task.member_id.id)
        if self._mode(owner) == 'finance' and task.kind != 'pledge': raise ValueError('Choose a financial task for finance staff.')
        if self._mode(owner) == 'volunteer' and task.kind != 'visitor': raise ValueError('Volunteers can receive visitor tasks only.')
        task.with_context(church_ops_actor=staff.id).write({'due_date': due, 'assigned_to_id': owner.id})
        return {'task': self._task_row(task)}

    def _visitors(self, staff, data):
        if self._mode(staff) == 'finance': raise AccessError('Visitor access is not enabled for finance staff.')
        domain = self._people_domain(staff) + [('visitor_stage', '!=', False)]
        if data.get('stage'): domain.append(('visitor_stage', '=', data['stage']))
        if data.get('overdue'): domain.append(('church_next_contact_date', '<=', self._today(staff)))
        if data.get('query'): domain.append(('name', 'ilike', str(data['query'])[:100]))
        return self._page(self.env['res.partner'].sudo(), domain, data, lambda r: {
            'id': r.id, 'name': r.name, 'stage': r.visitor_stage, 'phone': r.phone or '',
            'owner': r.church_visitor_owner_id.name or 'Unassigned', 'owner_id': r.church_visitor_owner_id.id or None,
            'next_date': str(r.church_next_contact_date) if r.church_next_contact_date else '',
            'first_visit': str(r.first_visit_date) if r.first_visit_date else ''})

    def _contact(self, staff, data):
        member = self._member(staff, data.get('member_id'))
        outcome = str(data.get('outcome') or '').strip()
        method = data.get('method', 'call')
        if not outcome or method not in ('call', 'visit', 'message', 'other'):
            raise ValueError('Choose a contact method and record the outcome.')
        owner = self._staff(data.get('owner_id') or staff.id)
        if owner != staff and staff.staff_role not in ('admin', 'pastor'):
            raise AccessError('You cannot reassign this follow-up.')
        if self._mode(owner) == 'finance': raise ValueError('Choose a pastor, Admin or church volunteer.')
        next_date = fields.Date.to_date(data.get('next_date')) if data.get('next_date') else False
        if member.visitor_stage:
            stage = data.get('stage') or member.visitor_stage
            if stage not in STAGES: raise ValueError('Choose a visitor stage.')
            # Stage transitions continue through the existing membership rules.
            if staff.staff_role in ('admin', 'pastor'):
                result = member.with_context(church_ops_actor=staff.id).app_update_visitor(member.id, {'stage': stage}, requester_staff_id=staff.id)
                if result.get('success') is not True: raise AccessError(result.get('error'))
            elif stage != member.visitor_stage:
                if stage == 'joined': raise AccessError('A pastor or Admin must confirm membership.')
                member.with_context(church_ops_actor=staff.id).write({'visitor_stage': stage})
            member.with_context(church_ops_actor=staff.id).write({'church_visitor_owner_id': owner.id,
                'church_next_contact_date': next_date})
        else:
            self._member(owner, member.id)
        contact = self.env['church.ops.contact'].sudo().create({'member_id': member.id,
            'staff_id': staff.id, 'method': method, 'outcome': outcome, 'next_date': next_date})
        if next_date:
            self._save_task(staff, {'member_id': member.id, 'owner_id': owner.id,
                'kind': 'visitor' if member.visitor_stage else 'follow_up',
                'due_date': str(next_date), 'name': 'Follow up with ' + member.name})
        audit(self.env, contact._name, contact.id, member.id, 'Contact recorded')
        return {'contact_id': contact.id}

    def _contacts(self, staff, data):
        member = self._member(staff, data.get('member_id'))
        return self._page(self.env['church.ops.contact'].sudo(), [('member_id', '=', member.id)], data,
            lambda r: {'id': r.id, 'method': r.method, 'outcome': r.outcome, 'staff': r.staff_id.name,
                'date': str(r.create_date), 'next_date': str(r.next_date) if r.next_date else ''})

    def _timeline(self, staff, data):
        self._people(staff)
        member = self._member(staff, data.get('member_id'))
        # ID paging over audit entries is stable, while existing care visits and
        # attendance each have their own independent cursor on this screen.
        kind = data.get('kind', 'changes')
        if kind == 'changes':
            domain = [('member_id', '=', member.id)]
            if staff.staff_role != 'admin':
                domain.append(('source_model', 'in', ['res.partner', 'church.ops.task', 'church.ops.contact']))
            return self._page(self.env['church.ops.audit'].sudo(), domain, data,
                lambda r: {'id': r.id, 'name': r.action, 'date': str(r.create_date),
                    'detail': r.changed_fields or '', 'staff': r.staff_id.name or r.odoo_user_id.name})
        if kind == 'attendance':
            return self._page(self.env['church.event.attendance'].sudo(), [('member_id', '=', member.id)], data,
                lambda r: {'id': r.id, 'name': r.event_id.name, 'date': str(r.check_in_time), 'detail': r.method})
        if kind == 'care':
            domain = [('member_id', '=', member.id)]
            if self._mode(staff) != 'all':
                domain += expression.OR([[('author_id', '=', staff.id)], [('visible_to_senior_pastor_only', '=', False)]])
            return self._page(self.env['pastoral.care.note'].sudo(), domain, data,
                lambda r: {'id': r.id, 'name': r.note_type.replace('_', ' ').title(), 'date': str(r.date),
                    'detail': 'Care visit recorded', 'staff': r.author_id.name})
        raise ValueError('Choose a timeline category.')

    def _attendance(self, staff, data):
        self._people(staff)
        count = data.get('missed_services', 3)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 12:
            raise ValueError('Choose between 1 and 12 services.')
        service_type = data.get('service_type', 'sabbath_worship')
        domain = [('date_start', '<', fields.Datetime.now())]
        if service_type: domain.append(('service_type', '=', service_type))
        services = self.env['church.service'].sudo().search(domain, order='date_start desc, id desc', limit=count)
        people = self.env['res.partner'].sudo().search(self._people_domain(staff) + [('is_member', '=', True)]).ids
        attendance = self.env['church.event.attendance'].sudo()
        recent = attendance._read_group([('event_id', 'in', services.ids), ('member_id', 'in', people)], ['member_id'], ['__count'])
        seen = [person.id for person, _number in recent]
        missing_domain = [('id', 'in', people), ('id', 'not in', seen),
            ('membership_status', 'in', ['member', 'worker', 'leader', 'new_convert'])]
        if len(services) < count:
            missing_domain.append(('id', '=', 0))
        elif services:
            earliest = min(services.mapped('date_start')).date()
            missing_domain += expression.OR([[('member_join_date', '=', False)], [('member_join_date', '<=', earliest)]])
        result = self._page(self.env['res.partner'].sudo(), missing_domain, data,
            lambda r: {'id': r.id, 'name': r.name, 'phone': r.phone or ''})
        cutoff = fields.Datetime.now() - timedelta(weeks=8)
        trend = attendance.with_context(tz=staff.user_id.tz or 'UTC')._read_group([
            ('check_in_time', '>=', cutoff), ('member_id', 'in', people)], ['check_in_time:week'], ['__count'])
        result.update(trend=[{'week': str(day), 'count': total} for day, total in trend],
            services=[{'name': r.name, 'date': str(r.date_start)} for r in services],
            definition='No recorded attendance in all of these selected services. Review before contacting.')
        return result

    def _tx(self, staff, tx_id):
        self._finance(staff)
        tx = self.env['church.give.transaction'].sudo().browse(positive_id(tx_id)).exists()
        if not tx: raise ValueError('Donation not found.')
        return tx

    def _finance_list(self, staff, data):
        self._finance(staff)
        txs = self.env['church.give.transaction'].sudo()
        domain = []
        state = data.get('state')
        if state: domain.append(('state', '=', state))
        if data.get('unverified'): domain += [('state', '=', 'completed'), ('church_reconciled', '=', False)]
        def row(tx):
            return {'id': tx.id, 'name': tx.reference or str(tx.id),
                'donor': 'Anonymous' if tx.is_anonymous else tx.donor_name or '',
                'state': tx.state, 'amount': tx.amount, 'currency': tx.currency,
                'net': tx.church_net_amount, 'refunded': tx.amount - tx.church_net_amount,
                'date': str(tx.transaction_date), 'verified': tx.church_reconciled,
                'pledge_currency': tx.pledge_id.currency if tx.pledge_id else '',
                'needs_credit': bool(tx.pledge_id and tx.pledge_id.currency not in ('PKR', tx.currency) and not tx.church_credit_verified)}
        result = self._page(txs, domain, data, row)
        sums = txs._read_group([('state', 'in', ['completed', 'refunded'])], ['currency'], ['amount:sum', 'church_net_amount:sum'])
        result['totals'] = [{'currency': cur, 'gross': gross, 'net': net, 'refunded': gross-net} for cur, gross, net in sums]
        result['notice'] = 'Verification records statement checks. Refund entries record money already returned; no payment is issued here.'
        return result

    def _reconcile(self, staff, data):
        tx = self._tx(staff, data.get('transaction_id'))
        amount = money(data.get('amount'), zero=True)
        currency = str(data.get('currency') or '')
        reference = str(data.get('reference') or '').strip()[:180]
        if not reference: raise ValueError('A statement or payment reference is required.')
        matched = currency == tx.currency and amount == money(tx.amount, zero=True) and tx.state == 'completed'
        entry = self.env['church.ops.reconcile'].sudo().create({'transaction_id': tx.id,
            'staff_id': staff.id, 'state': 'matched' if matched else 'discrepancy',
            'reference': reference, 'statement_amount': float(amount), 'currency': currency,
            'note': str(data.get('note') or '')})
        values = {'church_reconciled': matched}
        if data.get('pledge_credit') not in (None, ''):
            if not matched or not tx.pledge_id: raise ValueError('Pledge credit requires a matched donation linked to a pledge.')
            values.update(church_pledge_credit=float(money(data['pledge_credit'])), church_credit_verified=True)
        tx.with_context(church_ops_actor=staff.id, church_ops_reconcile=True).write(values)
        audit(self.env, entry._name, entry.id, tx.partner_id.id, 'Donation reconciliation recorded')
        return {'matched': matched, 'reconciliation_id': entry.id}

    def _refund(self, staff, data):
        if staff.staff_role != 'admin': raise AccessError('An Admin must record a processed refund.')
        tx = self._tx(staff, data.get('transaction_id'))
        self.env.cr.execute('SELECT id FROM church_give_transaction WHERE id = %s FOR UPDATE', [tx.id])
        tx.invalidate_recordset()
        if tx.state != 'completed': raise ValueError('Only a completed donation can have a refund recorded.')
        amount = money(data.get('amount'))
        returned = sum(tx.church_refund_ids.mapped('amount'))
        if amount > money(tx.amount) - money(returned, zero=True): raise ValueError('Refund exceeds the remaining donation amount.')
        reference, reason = str(data.get('reference') or '').strip(), str(data.get('reason') or '').strip()
        if not reference or not reason: raise ValueError('Provide the processed refund reference and reason.')
        rec = self.env['church.ops.refund'].sudo().create({'transaction_id': tx.id, 'amount': float(amount),
            'staff_id': staff.id, 'reference': reference, 'reason': reason})
        if amount + money(returned, zero=True) == money(tx.amount):
            tx.with_context(church_ops_actor=staff.id).write({'state': 'refunded'})
        audit(self.env, rec._name, rec.id, tx.partner_id.id, 'Processed refund recorded')
        return {'refund_id': rec.id}

    def _receipt(self, staff, data):
        tx = self._tx(staff, data.get('transaction_id'))
        if tx.state not in ('completed', 'refunded'):
            raise ValueError('A receipt is available only for a completed or refunded donation.')
        audit(self.env, tx._name, tx.id, tx.partner_id.id, 'Receipt viewed')
        return {'receipt': {'number': 'CR-R-%08d' % tx.id,
            'donor': 'Anonymous' if tx.is_anonymous else tx.donor_name or 'Donor',
            'date': str(tx.transaction_date), 'currency': tx.currency, 'amount': tx.amount,
            'refunded': tx.amount-tx.church_net_amount, 'net': tx.church_net_amount,
            'fund': tx.fund_id.name or 'Unrestricted', 'method': tx.gateway,
            'reference': tx.reference or '', 'state': tx.state,
            'verified': tx.church_reconciled}}

    def _audit_list(self, staff, data):
        if staff.staff_role != 'admin': raise AccessError('Only Admin may view the church audit trail.')
        return self._page(self.env['church.ops.audit'].sudo(), [], data, lambda r: {
            'id': r.id, 'name': r.action, 'date': str(r.create_date),
            'staff': r.staff_id.name or r.odoo_user_id.name or 'System',
            'detail': r.changed_fields or '', 'record': '%s #%s' % (r.source_model, r.source_id)})
