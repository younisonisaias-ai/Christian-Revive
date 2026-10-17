"""Apply the same active-role and assignment checks to existing church RPCs."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.osv import expression
from .models import audit


def guard(model, staff_id, member_ids=(), roles=('admin', 'pastor')):
    ops = model.env['church.operations']
    staff = ops._staff(staff_id)
    if staff.staff_role not in roles:
        raise AccessError('Your church role cannot perform this action.')
    for member_id in member_ids:
        ops._member(staff, member_id)
    return staff


class MemberGuard(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _church_caller_scope(self, requester_partner_id=None, requester_staff_id=None):
        if requester_staff_id:
            try:
                guard(self, requester_staff_id)
            except (AccessError, ValueError):
                return 'denied', None
        return super()._church_caller_scope(requester_partner_id, requester_staff_id)

    @api.model
    def app_update_member(self, member_id, vals, requester_partner_id=None, requester_staff_id=None):
        if requester_staff_id: guard(self, requester_staff_id, [member_id])
        return super(MemberGuard, self.with_context(church_ops_actor=requester_staff_id or False)).app_update_member(
            member_id, vals, requester_partner_id, requester_staff_id)

    @api.model
    def app_verify_family_member(self, member_id, requester_staff_id=None):
        guard(self, requester_staff_id, [member_id])
        return super(MemberGuard, self.with_context(church_ops_actor=requester_staff_id)).app_verify_family_member(member_id, requester_staff_id)

    @api.model
    def app_add_visitor(self, vals, service_id=None, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        result = super(MemberGuard, self.with_context(church_ops_actor=staff.id)).app_add_visitor(vals, service_id, staff.id)
        if result.get('success'):
            visitor = self.sudo().browse(result['visitor_id'])
            due = fields.Date.add(fields.Date.context_today(self), days=3)
            visitor.with_context(church_ops_actor=staff.id).write({
                'church_visitor_owner_id': staff.id, 'church_next_contact_date': due})
            self.env['church.ops.task'].sudo().create({'name': 'Welcome ' + visitor.name,
                'member_id': visitor.id, 'assigned_to_id': staff.id, 'created_by_id': staff.id,
                'due_date': due, 'kind': 'visitor'})
            audit(self.env, 'res.partner', visitor.id, visitor.id, 'Visitor registered')
        return result

    @api.model
    def app_update_visitor(self, visitor_id, vals, requester_staff_id=None):
        staff = guard(self, requester_staff_id, [visitor_id])
        return super(MemberGuard, self.with_context(church_ops_actor=staff.id)).app_update_visitor(visitor_id, vals, staff.id)


class FamilyGuard(models.Model):
    _inherit = 'church.family'
    church_created_by_id = fields.Many2one('hr.employee', readonly=True)

    def _ops_family(self, family_id, staff):
        family = self.sudo().browse(family_id).exists()
        if not family: raise AccessError('Family not found.')
        ops = self.env['church.operations']
        if ops._mode(staff) != 'all' and family.church_created_by_id != staff:
            people = self.env['res.partner'].sudo().search(ops._people_domain(staff)).ids
            if not any(r.id in people for r in family.member_ids):
                raise AccessError('This household is outside your assignment.')
        return family

    @api.model
    def app_get_families(self, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        result = super().app_get_families(requester_staff_id)
        if result.get('success') and self.env['church.operations']._mode(staff) != 'all':
            people = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
            allowed = self.sudo().search(expression.OR([
                [('member_ids', 'in', people)], [('church_created_by_id', '=', staff.id)]])).ids
            result['families'] = [r for r in result['families'] if r['id'] in allowed]
        return result

    @api.model
    def app_get_family_detail(self, family_id, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        self._ops_family(family_id, staff)
        result = super().app_get_family_detail(family_id, requester_staff_id)
        if result.get('success') and self.env['church.operations']._mode(staff) != 'all':
            people = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
            result['members'] = [r for r in result['members'] if r['id'] in people]
        return result

    @api.model
    def app_create_family(self, vals, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        result = super().app_create_family(vals, staff.id)
        if result.get('success'):
            self.sudo().browse(result['family_id']).write({'church_created_by_id': staff.id})
        return result

    @api.model
    def app_add_member_to_family(self, family_id, member_id, is_head=False, requester_staff_id=None):
        staff = guard(self, requester_staff_id, [member_id])
        family = self._ops_family(family_id, staff)
        if is_head and family.head_id and self.env['church.operations']._mode(staff) != 'all':
            self.env['church.operations']._member(staff, family.head_id.id)
        return super(FamilyGuard, self.with_context(church_ops_actor=staff.id)).app_add_member_to_family(
            family_id, member_id, is_head, staff.id)

    @api.model
    def app_remove_member_from_family(self, member_id, requester_staff_id=None):
        staff = guard(self, requester_staff_id, [member_id])
        return super(FamilyGuard, self.with_context(church_ops_actor=staff.id)).app_remove_member_from_family(member_id, staff.id)


class CareGuard(models.Model):
    _inherit = 'pastoral.care.note'

    @api.model
    def app_get_pastoral_notes(self, member_id, requester_staff_id=None):
        guard(self, requester_staff_id, [member_id])
        return super().app_get_pastoral_notes(member_id, requester_staff_id)

    @api.model
    def app_add_pastoral_note(self, member_id, vals, requester_staff_id=None):
        staff = guard(self, requester_staff_id, [member_id])
        result = super().app_add_pastoral_note(member_id, vals, staff.id)
        if result.get('success'): audit(self.env, self._name, result['note_id'], member_id, 'Care visit recorded')
        return result

    def _follow_up_domain(self, employee, is_senior_or_admin):
        domain = super()._follow_up_domain(employee, is_senior_or_admin)
        if not is_senior_or_admin:
            people = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(employee)).ids
            domain.append(('member_id', 'in', people))
        return domain

    @api.model
    def app_complete_follow_up(self, note_id, outcome='', next_follow_up_date=None, requester_staff_id=None):
        note = self.sudo().browse(note_id).exists()
        if not note: raise AccessError('Follow-up not found.')
        staff = guard(self, requester_staff_id, [note.member_id.id])
        result = super(CareGuard, self.with_context(church_ops_actor=staff.id)).app_complete_follow_up(
            note_id, outcome, next_follow_up_date, staff.id)
        if result.get('success'): audit(self.env, self._name, note.id, note.member_id.id, 'Care follow-up updated')
        return result


class GroupGuard(models.Model):
    _inherit = 'cell.group'

    @api.model
    def app_get_cell_group_detail(self, group_id, requester_partner_id=None, requester_staff_id=None):
        result = super().app_get_cell_group_detail(group_id, requester_partner_id, requester_staff_id)
        if requester_staff_id and result.get('success'):
            staff = guard(self, requester_staff_id)
            if self.env['church.operations']._mode(staff) != 'all':
                ids = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
                result['group']['members'] = [r for r in result['group']['members'] if r['id'] in ids]
        return result

    @api.model
    def app_add_member_to_group(self, group_id, member_id, requester_partner_id=None, requester_staff_id=None):
        if requester_staff_id:
            guard(self, requester_staff_id, [member_id])
            if not self.app_get_cell_group_detail(group_id, requester_staff_id=requester_staff_id).get('success'):
                raise AccessError('This group is outside your assignment.')
        result = super().app_add_member_to_group(group_id, member_id, requester_partner_id, requester_staff_id)
        if result.get('success'):
            audit(self.with_context(church_ops_actor=requester_staff_id or False).env,
                self._name, group_id, member_id, 'Group roster updated')
        return result


class AttendanceGuard(models.Model):
    _inherit = 'church.event.attendance'

    @api.model
    def app_check_in(self, event_id=None, member_id=None, requester_partner_id=None,
                     requester_staff_id=None, service_id=None, member_code=None, method=None):
        if requester_staff_id:
            if member_code and not member_id:
                member_id = self._member_from_code(member_code).id
            guard(self, requester_staff_id, [member_id] if member_id else [])
        return super().app_check_in(event_id, member_id, requester_partner_id,
            requester_staff_id, service_id, member_code, method)

    @api.model
    def app_get_event_attendance(self, event_id, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        result = super().app_get_event_attendance(event_id, requester_staff_id)
        if result.get('success') and self.env['church.operations']._mode(staff) != 'all':
            ids = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
            result['attendance'] = [row for row in result['attendance'] if row['member_id'][0] in ids]
        return result


class PledgeGuard(models.Model):
    _inherit = 'church.give.pledge'

    @api.model
    def app_get_pledges(self, requester_staff_id, status=None):
        staff = guard(self, requester_staff_id, roles=('admin', 'pastor', 'finance_officer'))
        result = super().app_get_pledges(requester_staff_id, status)
        if result.get('success') and staff.staff_role == 'pastor' and not staff.is_senior_pastor:
            ids = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
            result['pledges'] = [r for r in result['pledges'] if r['member_id'] in ids]
        return result

    @api.model
    def app_create_pledge(self, vals, requester_partner_id=None, requester_staff_id=None):
        if requester_staff_id:
            staff = guard(self, requester_staff_id, roles=('admin', 'pastor', 'finance_officer'))
            if staff.staff_role == 'pastor': self.env['church.operations']._member(staff, (vals or {}).get('member_id'))
        return super().app_create_pledge(vals, requester_partner_id, requester_staff_id)


class ReportGuard(models.TransientModel):
    _inherit = 'church.report'

    def _staff_role(self, requester_staff_id):
        try:
            return guard(self, requester_staff_id, roles=('admin', 'pastor', 'finance_officer')).staff_role
        except (ValueError, AccessError):
            return None

    @api.model
    def app_get_giving_by_fund(self, requester_staff_id=None):
        guard(self, requester_staff_id, roles=('admin', 'finance_officer'))
        txs = self.env['church.give.transaction'].sudo()
        domain = [('state', '=', 'completed')]
        return {'success': True,
            'by_fund': [{'fund': rec.name if rec else 'Unrestricted', 'total_pkr': amount}
                for rec, amount in txs._read_group(domain, ['fund_id'], ['church_net_pkr:sum'])],
            'by_category': [{'category': rec.name if rec else 'Other', 'total_pkr': amount}
                for rec, amount in txs._read_group(domain, ['category_id'], ['church_net_pkr:sum'])]}

    @api.model
    def app_get_membership_growth(self, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        partner = self.env['res.partner'].sudo()
        domain = self.env['church.operations']._people_domain(staff) + [('is_member', '=', True)]
        by_status = [{'status': status or 'visitor', 'count': count}
            for status, count in partner._read_group(domain, ['membership_status'], ['__count'])]
        monthly = partner._read_group(domain + [('member_join_date', '!=', False)], ['member_join_date:month'], ['__count'])
        return {'success': True, 'by_status': by_status,
                'by_month': [{'month': str(day)[:7], 'new_members': count} for day, count in monthly]}

    @api.model
    def app_get_attendance_trends(self, requester_staff_id=None):
        staff = guard(self, requester_staff_id)
        ids = self.env['res.partner'].sudo().search(self.env['church.operations']._people_domain(staff)).ids
        rows = self.env['church.event.attendance'].sudo()._read_group([('member_id', 'in', ids)], ['event_id'], ['__count'])
        return {'success': True, 'by_event': [{'event': rec.name, 'attendance_count': count} for rec, count in rows]}


class FundGuard(models.Model):
    _inherit = 'church.give.fund'

    @api.model
    def app_get_funds(self, requester_staff_id=None):
        result = super().app_get_funds()
        can_read = False
        if requester_staff_id:
            try:
                can_read = guard(self, requester_staff_id,
                    roles=('admin', 'finance_officer')).staff_role in ('admin', 'finance_officer')
            except (AccessError, ValueError):
                pass
        if result.get('success') and not can_read:
            for row in result['funds']: row.pop('total_contributed', None)
        return result

    @api.model
    def app_create_fund(self, vals, requester_staff_id=None):
        guard(self, requester_staff_id, roles=('admin', 'finance_officer'))
        return super().app_create_fund(vals, requester_staff_id)

    def _compute_total_contributed(self):
        for fund in self:
            rows = self.env['church.give.transaction'].sudo()._read_group([
                ('fund_id', '=', fund.id), ('state', '=', 'completed')], [], ['church_net_pkr:sum'])
            fund.total_contributed = rows[0][0] if rows else 0


class MobileReport(models.AbstractModel):
    _inherit = 'church.dashboard'

    def _giving(self, today):
        start = today.replace(day=1)
        previous = (start - timedelta(days=1)).replace(day=1)
        following = (start + timedelta(days=32)).replace(day=1)
        txs = self.env['church.give.transaction'].sudo()
        def total(first, last):
            domain = [('state', '=', 'completed'), ('transaction_date', '>=', datetime.combine(first, time.min)),
                ('transaction_date', '<', datetime.combine(last, time.min))]
            values = txs._read_group(domain, [], ['church_net_pkr:sum', '__count'])
            return values[0] if values else (0, 0)
        current, count = total(start, following)
        old, _ = total(previous, start)
        return {'this_month_pkr': round(current), 'this_month_count': count, 'last_month_pkr': round(old)}

    def _report_admin(self, staff_id):
        try:
            return guard(self, staff_id, roles=('admin',))
        except (ValueError, AccessError):
            return None

    @api.model
    def app_report_manifest(self, requester_staff_id=None, options=None):
        result = super().app_report_manifest(requester_staff_id, options)
        if not result.get('success'): return result
        from odoo.addons.church_report_mobile.report_rules import validate
        opts = validate(options)
        staff = self._report_admin(requester_staff_id)
        if 'giving' in opts['sections']:
            model, domain = self._report_source('donations', opts, staff)
            result['summaries']['giving'] = {
                'by_fund': [{'fund': rec.name if rec else 'Unrestricted', 'total_pkr': value}
                    for rec, value in model._read_group(domain, ['fund_id'], ['church_net_pkr:sum'])],
                'by_category': [{'category': rec.name if rec else 'Other', 'total_pkr': value}
                    for rec, value in model._read_group(domain, ['category_id'], ['church_net_pkr:sum'])]}
        if opts['member_ids']:
            model, domain = self._report_source('donations', opts, staff)
            given = {rec.id: value for rec, value in model._read_group(domain, ['partner_id'], ['church_net_pkr:sum']) if rec}
            pledges, pdomain = self._report_source('pledges', opts, staff)
            amounts, paid = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(float))
            for pledge in pledges.search(pdomain):
                amounts[pledge.member_id.id][pledge.currency] += pledge.pledge_amount
                paid[pledge.member_id.id][pledge.currency] += pledge.paid_amount
            for row in result['summaries'].get('member_summary', {}).get('rows', []):
                row['given_pkr'] = given.get(row['id'], 0)
                row['pledged_display'] = ' / '.join('%s %.2f' % (c, v) for c, v in sorted(amounts[row['id']].items())) or '-'
                row['paid_display'] = ' / '.join('%s %.2f' % (c, v) for c, v in sorted(paid[row['id']].items())) or '-'
        return result
