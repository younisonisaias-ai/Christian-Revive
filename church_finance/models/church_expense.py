from datetime import date
from decimal import Decimal

from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from . import expense_rules as rules

LIMIT_PARAM = 'church_finance.expense_approval_limit'
CURRENCY_SELECTION = [(c, c) for c in rules.CURRENCIES]
METHOD_SELECTION = [('cash', 'Cash'), ('bank', 'Bank transfer'), ('cheque', 'Cheque'),
                    ('mobile', 'Mobile wallet'), ('other', 'Other')]
STATE_SELECTION = [('draft', 'Draft'), ('submitted', 'Waiting for approval'),
                   ('approved', 'Approved'), ('paid', 'Paid'),
                   ('rejected', 'Rejected'), ('reversed', 'Reversed')]
# Fields that may change only while an expense is a draft or was sent back.
LOCKED_FIELDS = {'date', 'category_id', 'fund_id', 'description', 'payee', 'amount',
                 'currency', 'amount_pkr', 'receipt', 'receipt_filename', 'notes'}


class ChurchExpenseCategory(models.Model):
    _name = 'church.expense.category'
    _description = 'Church Expense Category'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    fund_id = fields.Many2one('church.give.fund', string='Default fund',
        help='Spending in this category comes from this fund unless the expense says otherwise.')
    description = fields.Text()
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint('unique(name)', 'An expense category with this name already exists.')


class ChurchExpense(models.Model):
    _name = 'church.expense'
    _description = 'Church Expense'
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='/')
    date = fields.Date(required=True, default=fields.Date.context_today)
    category_id = fields.Many2one('church.expense.category', required=True, index=True, ondelete='restrict')
    fund_id = fields.Many2one('church.give.fund', string='Paid from fund', index=True, ondelete='restrict')
    description = fields.Char(required=True)
    payee = fields.Char(string='Paid to')
    amount = fields.Float(required=True, digits=(16, 2))
    currency = fields.Selection(CURRENCY_SELECTION, required=True, default='PKR')
    amount_pkr = fields.Float(string='Amount (PKR)', required=True, digits=(16, 2),
        help='The PKR actually paid. Budgets and approval limits use this figure.')
    method = fields.Selection(METHOD_SELECTION, string='Payment method')
    reference = fields.Char(string='Payment reference')
    notes = fields.Text()
    receipt = fields.Binary(attachment=True)
    receipt_filename = fields.Char()
    state = fields.Selection(STATE_SELECTION, default='draft', required=True, index=True)
    submitted_by_id = fields.Many2one('hr.employee', string='Recorded by', required=True, index=True)
    submitted_at = fields.Datetime(readonly=True)
    approved_by_id = fields.Many2one('hr.employee', readonly=True)
    approved_at = fields.Datetime(readonly=True)
    paid_by_id = fields.Many2one('hr.employee', readonly=True)
    paid_at = fields.Datetime(readonly=True)
    rejected_reason = fields.Text(readonly=True)
    reversed_by_id = fields.Many2one('hr.employee', readonly=True)
    reversed_at = fields.Datetime(readonly=True)
    reversal_reason = fields.Text(readonly=True)
    request_key = fields.Char(index=True, copy=False)
    log_ids = fields.One2many('church.expense.log', 'expense_id', string='History')

    _unique_request = models.Constraint('unique(submitted_by_id, request_key)',
        'This expense was already saved.')

    @api.constrains('amount', 'amount_pkr')
    def _check_amounts(self):
        for rec in self:
            if rec.amount <= 0 or rec.amount_pkr <= 0:
                raise ValidationError('Expense amounts must be greater than zero.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('church.expense') or '/'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('church_expense_internal'):
            locked = LOCKED_FIELDS & set(vals)
            if locked and any(rec.state not in ('draft', 'rejected') for rec in self):
                raise UserError('Submitted, approved or paid expenses cannot be changed. '
                                'An Admin can reverse a paid expense instead.')
            if 'state' in vals:
                raise UserError('Use the approval buttons to change an expense status.')
        return super().write(vals)

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError('Only draft expenses can be deleted. Reverse a paid expense instead.')
        return super().unlink()

    # ── Shared helpers ──────────────────────────────────────────

    def _log(self, staff, action, note=''):
        self.env['church.expense.log'].sudo().with_context(church_expense_internal=True).create({
            'expense_id': self.id, 'staff_id': staff.id, 'action': action, 'note': note or False})

    def _as_rule(self):
        return {'state': self.state, 'submitted_by': self.submitted_by_id.id,
                'amount_pkr': self.amount_pkr}

    @api.model
    def _approval_limit(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(LIMIT_PARAM)
        try:
            return rules.money(raw) if raw else rules.DEFAULT_APPROVAL_LIMIT
        except ValueError:
            return rules.DEFAULT_APPROVAL_LIMIT

    def _row(self, staff=None):
        return {'id': self.id, 'name': self.name, 'date': str(self.date),
            'description': self.description, 'payee': self.payee or '',
            'category': self.category_id.name, 'category_id': self.category_id.id,
            'fund': self.fund_id.name or '', 'fund_id': self.fund_id.id or None,
            'amount': self.amount, 'currency': self.currency, 'amount_pkr': self.amount_pkr,
            'state': self.state, 'submitted_by': self.submitted_by_id.name,
            'submitted_by_id': self.submitted_by_id.id, 'has_receipt': bool(self.receipt)}

    def _detail(self, staff):
        row = self._row()
        role = staff.staff_role
        limit = self._approval_limit()
        row.update({
            'method': self.method or '', 'reference': self.reference or '', 'notes': self.notes or '',
            'receipt_filename': self.receipt_filename or '',
            'approved_by': self.approved_by_id.name or '', 'approved_at': str(self.approved_at or ''),
            'paid_by': self.paid_by_id.name or '', 'paid_at': str(self.paid_at or ''),
            'rejected_reason': self.rejected_reason or '', 'reversal_reason': self.reversal_reason or '',
            'history': [{'action': log.action, 'note': log.note or '', 'staff': log.staff_id.name or '',
                         'date': str(log.create_date)} for log in self.log_ids.sorted('id')],
            'can_edit': rules.can_edit(role, staff.id, self._as_rule()),
            'can_submit': self.state in ('draft', 'rejected') and rules.can_edit(role, staff.id, self._as_rule()),
            'can_approve': rules.approval_problem(role, staff.id, self._as_rule(), limit) is None,
            'can_pay': rules.payment_problem(role, self._as_rule()) is None,
            'can_reverse': rules.reversal_problem(role, self._as_rule()) is None,
            'approval_note': rules.approval_problem(role, staff.id, self._as_rule(), limit)
                if self.state == 'submitted' else '',
        })
        return row

    # ── App entry point ─────────────────────────────────────────

    @api.model
    def app_church_finance(self, requester_staff_id=None, action='', payload=None):
        """Single scoped entry point for the app's expense & budget screens."""
        handlers = {
            'home': self._api_home, 'options': self._api_options, 'list': self._api_list,
            'get': self._api_get, 'receipt': self._api_receipt, 'save': self._api_save,
            'submit': self._api_submit, 'approve': self._api_approve, 'reject': self._api_reject,
            'pay': self._api_pay, 'reverse': self._api_reverse, 'delete': self._api_delete,
            'budget': self._api_budget, 'budget_save': self._api_budget_save,
            'category_save': self._api_category_save, 'funds': self._api_funds,
            'report': self._api_report, 'set_limit': self._api_set_limit,
        }
        try:
            staff = self._finance_staff(requester_staff_id)
            if action not in handlers:
                raise ValueError('Unknown finance action.')
            if payload is not None and not isinstance(payload, dict):
                raise ValueError('Invalid request.')
            with self.env.cr.savepoint():
                return {'success': True, **handlers[action](staff, dict(payload or {}))}
        except AccessError as exc:
            return {'success': False, 'code': 'denied', 'error': str(exc)}
        except (UserError, ValidationError, ValueError, TypeError, KeyError) as exc:
            return {'success': False, 'code': 'invalid', 'error': str(exc) or 'Check the form and retry.'}
        except IntegrityError:
            # Two taps of the same save raced; a retry replays the saved result.
            return {'success': False, 'code': 'retry', 'error': 'This save is already processing. Please retry.'}

    def _finance_staff(self, staff_id):
        if isinstance(staff_id, bool) or not isinstance(staff_id, int) or staff_id <= 0:
            raise AccessError('Please sign in again.')
        staff = self.env['hr.employee'].sudo().browse(staff_id).exists()
        if not staff or not staff.active or ('is_app_active' in staff._fields and not staff.is_app_active):
            raise AccessError('Your staff access is not enabled.')
        if staff.staff_role not in rules.SUBMITTERS:
            raise AccessError('Your role does not have access to church spending.')
        return staff

    def _manager(self, staff):
        if staff.staff_role not in rules.MANAGERS:
            raise AccessError('Finance or Admin access is required.')

    def _id(self, raw, message='Choose a valid record.'):
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            raise ValueError(message)
        return raw

    def _date(self, raw, default=None):
        if raw in (None, ''):
            return default
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            raise ValueError('Choose a valid date.')

    def _visible_domain(self, staff):
        return [] if rules.can_view_all(staff.staff_role) else [('submitted_by_id', '=', staff.id)]

    def _get(self, staff, raw_id, lock=False):
        expense_id = self._id(raw_id)
        if lock:
            self.env.cr.execute('SELECT id FROM church_expense WHERE id = %s FOR UPDATE', [expense_id])
        rec = self.sudo().search([('id', '=', expense_id)] + self._visible_domain(staff), limit=1)
        if not rec:
            raise AccessError('This expense is not available to you.')
        if lock:
            rec.invalidate_recordset()
        return rec

    def _today(self, staff):
        return fields.Date.context_today(self.with_context(tz=staff.user_id.tz or 'Asia/Karachi'))

    def _income_domain(self, date_from=None, date_to=None):
        domain = [('state', '=', 'completed')]
        if date_from:
            domain.append(('transaction_date', '>=', fields.Datetime.to_datetime(date_from)))
        if date_to:
            domain.append(('transaction_date', '<', fields.Datetime.to_datetime(
                fields.Date.add(date_to, days=1))))
        return domain

    def _income_field(self):
        # Net of recorded refunds when Church Operations is installed.
        tx = self.env['church.give.transaction']
        return 'church_net_pkr' if 'church_net_pkr' in tx._fields else 'amount_pkr'

    def _spent(self, domain):
        rows = self.sudo()._read_group(domain, [], ['amount_pkr:sum'])
        return rows[0][0] if rows else 0.0

    # ── Handlers ────────────────────────────────────────────────

    def _api_home(self, staff, data):
        today = self._today(staff)
        month_start = today.replace(day=1)
        manager = staff.staff_role in rules.MANAGERS
        limit = self._approval_limit()
        result = {'role': staff.staff_role, 'staff_name': staff.name, 'can_manage': manager,
                  'is_admin': staff.staff_role == 'admin', 'approval_limit': float(limit),
                  'my_drafts': self.sudo().search_count([('submitted_by_id', '=', staff.id),
                      ('state', 'in', ['draft', 'rejected'])])}
        if manager:
            waiting = self.sudo().search([('state', '=', 'submitted'), ('submitted_by_id', '!=', staff.id)])
            if staff.staff_role == 'finance_officer':
                waiting = waiting.filtered(lambda e: Decimal(str(e.amount_pkr)) <= limit)
            income = self.env['church.give.transaction'].sudo()._read_group(
                self._income_domain(month_start, today), [], [self._income_field() + ':sum'])
            spent = self._spent([('state', '=', 'paid'), ('date', '>=', month_start), ('date', '<=', today)])
            result.update(
                to_approve=len(waiting),
                to_pay=self.sudo().search_count([('state', '=', 'approved')]),
                month={'income': income[0][0] if income else 0.0, 'spent': spent,
                       'net': (income[0][0] if income else 0.0) - spent, 'from': str(month_start)},
                budget_alerts=[line for line in self._budget_lines(today.year) if line['level'] != 'ok'][:6])
        return result

    def _api_options(self, staff, data):
        categories = self.env['church.expense.category'].sudo().search([])
        funds = self.env['church.give.fund'].sudo().search([('is_active', '=', True)])
        return {'categories': [{'id': c.id, 'name': c.name, 'fund_id': c.fund_id.id or None}
                               for c in categories],
                'funds': [{'id': f.id, 'name': f.name, 'type': f.fund_type} for f in funds],
                'currencies': list(rules.CURRENCIES),
                'methods': [{'id': k, 'name': v} for k, v in METHOD_SELECTION],
                'approval_limit': float(self._approval_limit())}

    def _api_list(self, staff, data):
        domain = list(self._visible_domain(staff))
        if data.get('mine'):
            domain.append(('submitted_by_id', '=', staff.id))
        state = data.get('state')
        if state == 'to_approve':
            self._manager(staff)
            domain += [('state', '=', 'submitted'), ('submitted_by_id', '!=', staff.id)]
            if staff.staff_role == 'finance_officer':
                domain.append(('amount_pkr', '<=', float(self._approval_limit())))
        elif state:
            if state not in rules.STATES:
                raise ValueError('Choose a status.')
            domain.append(('state', '=', state))
        if data.get('category_id'):
            domain.append(('category_id', '=', self._id(data['category_id'])))
        if data.get('fund_id'):
            domain.append(('fund_id', '=', self._id(data['fund_id'])))
        date_from, date_to = self._date(data.get('date_from')), self._date(data.get('date_to'))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        query = rules.clean_text(data.get('query'), 100)
        if query:
            domain += ['|', '|', '|', ('description', 'ilike', query), ('payee', 'ilike', query),
                       ('name', 'ilike', query), ('reference', 'ilike', query)]
        offset = data.get('offset', 0)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError('Invalid page.')
        records = self.sudo().search(domain, offset=offset, limit=41)
        return {'rows': [r._row() for r in records[:40]], 'has_more': len(records) > 40,
                'next_offset': offset + 40, 'total_pkr': self._spent(domain)}

    def _api_get(self, staff, data):
        return {'expense': self._get(staff, data.get('id'))._detail(staff)}

    def _api_receipt(self, staff, data):
        rec = self._get(staff, data.get('id'))
        if not rec.receipt:
            raise ValueError('No receipt is attached.')
        raw = rec.receipt
        return {'filename': rec.receipt_filename or 'receipt.jpg',
                'data': raw.decode() if isinstance(raw, bytes) else raw}

    def _api_save(self, staff, data):
        vals = {
            'date': self._date(data.get('date'), self._today(staff)),
            'category_id': self._id(data.get('category_id'), 'Choose a category.'),
            'description': rules.clean_text(data.get('description'), 180, 'Describe what the money was spent on.'),
            'payee': rules.clean_text(data.get('payee'), 120) or False,
            'notes': str(data.get('notes') or '').strip()[:2000] or False,
            'method': data.get('method') or False,
            'reference': rules.clean_text(data.get('reference'), 120) or False,
        }
        if vals['method'] and vals['method'] not in rules.METHODS:
            raise ValueError('Choose a payment method.')
        currency = data.get('currency') or 'PKR'
        amount = rules.money(data.get('amount'))
        vals.update(currency=currency, amount=float(amount),
                    amount_pkr=float(rules.pkr_amount(amount, currency, data.get('amount_pkr'))))
        category = self.env['church.expense.category'].sudo().browse(vals['category_id']).exists()
        if not category or not category.active:
            raise ValueError('Choose an active category.')
        fund_id = data.get('fund_id')
        vals['fund_id'] = self._id(fund_id) if fund_id else (category.fund_id.id or False)
        if vals['fund_id'] and not self.env['church.give.fund'].sudo().browse(vals['fund_id']).exists():
            raise ValueError('Choose a valid fund.')
        if 'receipt' in data:
            if data.get('receipt'):
                vals['receipt_filename'] = rules.check_receipt(data['receipt'], data.get('receipt_filename'))
                vals['receipt'] = data['receipt']
            else:
                vals.update(receipt=False, receipt_filename=False)
        key = rules.request_key(data.get('request_key'))

        if data.get('id'):
            rec = self._get(staff, data['id'], lock=True)
            if not rules.can_edit(staff.staff_role, staff.id, rec._as_rule()):
                raise AccessError('This expense can no longer be changed.')
            rec.sudo().write(vals)
            rec._log(staff, 'Edited')
        else:
            if key:
                previous = self.sudo().search([('submitted_by_id', '=', staff.id), ('request_key', '=', key)], limit=1)
                if previous:
                    return {'expense': previous._detail(staff), 'replayed': True}
            rec = self.sudo().create(dict(vals, submitted_by_id=staff.id, request_key=key or False))
            rec._log(staff, 'Recorded')
        if data.get('submit'):
            self._do_submit(staff, rec)
        return {'expense': rec._detail(staff)}

    def _do_submit(self, staff, rec):
        if not rules.can_edit(staff.staff_role, staff.id, rec._as_rule()):
            raise AccessError('This expense cannot be submitted.')
        rec.with_context(church_expense_internal=True).sudo().write({
            'state': 'submitted', 'submitted_at': fields.Datetime.now(), 'rejected_reason': False})
        rec._log(staff, 'Submitted for approval')

    def _api_submit(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        self._do_submit(staff, rec)
        return {'expense': rec._detail(staff)}

    def _api_approve(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        problem = rules.approval_problem(staff.staff_role, staff.id, rec._as_rule(), self._approval_limit())
        if problem:
            raise AccessError(problem)
        rec.with_context(church_expense_internal=True).sudo().write({
            'state': 'approved', 'approved_by_id': staff.id, 'approved_at': fields.Datetime.now()})
        rec._log(staff, 'Approved', rules.clean_text(data.get('note'), 300))
        return {'expense': rec._detail(staff)}

    def _api_reject(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        problem = rules.approval_problem(staff.staff_role, staff.id, rec._as_rule(), self._approval_limit())
        if problem:
            raise AccessError(problem.replace('approve', 'reject'))
        reason = rules.clean_text(data.get('reason'), 500, 'Give a reason so the person can correct it.')
        rec.with_context(church_expense_internal=True).sudo().write({
            'state': 'rejected', 'rejected_reason': reason})
        rec._log(staff, 'Sent back', reason)
        return {'expense': rec._detail(staff)}

    def _api_pay(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        problem = rules.payment_problem(staff.staff_role, rec._as_rule())
        if problem:
            raise AccessError(problem)
        method = data.get('method') or rec.method
        if method not in rules.METHODS:
            raise ValueError('Choose how it was paid.')
        rec.with_context(church_expense_internal=True).sudo().write({
            'state': 'paid', 'paid_by_id': staff.id, 'paid_at': fields.Datetime.now(), 'method': method,
            'reference': rules.clean_text(data.get('reference'), 120) or rec.reference or False})
        rec._log(staff, 'Marked as paid')
        return {'expense': rec._detail(staff)}

    def _api_reverse(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        problem = rules.reversal_problem(staff.staff_role, rec._as_rule())
        if problem:
            raise AccessError(problem)
        reason = rules.clean_text(data.get('reason'), 500, 'Give the reason for reversing this payment.')
        rec.with_context(church_expense_internal=True).sudo().write({
            'state': 'reversed', 'reversed_by_id': staff.id, 'reversed_at': fields.Datetime.now(),
            'reversal_reason': reason})
        rec._log(staff, 'Reversed', reason)
        return {'expense': rec._detail(staff)}

    def _api_delete(self, staff, data):
        rec = self._get(staff, data.get('id'), lock=True)
        if rec.state != 'draft' or not rules.can_edit(staff.staff_role, staff.id, rec._as_rule()):
            raise AccessError('Only your own draft expenses can be deleted.')
        rec.sudo().unlink()
        return {'deleted': True}

    # ── Budget, funds and reports ───────────────────────────────

    def _budget_lines(self, year):
        start, end = date(year, 1, 1), date(year, 12, 31)
        budget = self.env['church.budget'].sudo().search([('year', '=', year)], limit=1)
        paid = dict(self.sudo()._read_group(
            [('state', '=', 'paid'), ('date', '>=', start), ('date', '<=', end)],
            ['category_id'], ['amount_pkr:sum']))
        committed = dict(self.sudo()._read_group(
            [('state', 'in', ['submitted', 'approved']), ('date', '>=', start), ('date', '<=', end)],
            ['category_id'], ['amount_pkr:sum']))
        lines, seen = [], set()
        for line in budget.line_ids.sorted(lambda l: (l.category_id.sequence, l.category_id.name)):
            actual = paid.get(line.category_id, 0.0)
            seen.add(line.category_id.id)
            lines.append({'category_id': line.category_id.id, 'category': line.category_id.name,
                          'planned': line.amount, 'actual': actual,
                          'committed': committed.get(line.category_id, 0.0),
                          **rules.budget_status(line.amount, actual)})
        for category, actual in paid.items():
            if category.id not in seen:
                lines.append({'category_id': category.id, 'category': category.name, 'planned': 0.0,
                              'actual': actual, 'committed': committed.get(category, 0.0),
                              **rules.budget_status(0, actual)})
        return lines

    def _year(self, staff, raw):
        year = raw if raw not in (None, '') else self._today(staff).year
        if isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 2100:
            raise ValueError('Choose a valid year.')
        return year

    def _api_budget(self, staff, data):
        self._manager(staff)
        year = self._year(staff, data.get('year'))
        lines = self._budget_lines(year)
        budget = self.env['church.budget'].sudo().search([('year', '=', year)], limit=1)
        return {'year': year, 'exists': bool(budget), 'notes': budget.notes or '', 'lines': lines,
                'total_planned': sum(l['planned'] for l in lines),
                'total_actual': sum(l['actual'] for l in lines),
                'total_committed': sum(l['committed'] for l in lines)}

    def _api_budget_save(self, staff, data):
        self._manager(staff)
        year = self._year(staff, data.get('year'))
        rows = data.get('lines')
        if not isinstance(rows, list):
            raise ValueError('Enter the budget amounts.')
        planned = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Enter the budget amounts.')
            category_id = self._id(row.get('category_id'), 'Choose a category for each line.')
            planned[category_id] = float(rules.money(row.get('amount') or 0, zero=True))
        Budget = self.env['church.budget'].sudo()
        budget = Budget.search([('year', '=', year)], limit=1) or Budget.create({'year': year})
        existing = {l.category_id.id: l for l in budget.line_ids}
        for category_id, amount in planned.items():
            if category_id in existing:
                existing[category_id].write({'amount': amount})
            elif amount:
                budget.write({'line_ids': [(0, 0, {'category_id': category_id, 'amount': amount})]})
        if 'notes' in data:
            budget.write({'notes': str(data.get('notes') or '')[:2000] or False})
        budget.write({'updated_by_id': staff.id})
        return self._api_budget(staff, {'year': year})

    def _api_category_save(self, staff, data):
        self._manager(staff)
        Category = self.env['church.expense.category'].sudo().with_context(active_test=False)
        vals = {'name': rules.clean_text(data.get('name'), 80, 'Enter a category name.')}
        if 'fund_id' in data:
            vals['fund_id'] = self._id(data['fund_id']) if data.get('fund_id') else False
        if 'active' in data:
            vals['active'] = data.get('active') is not False
        if data.get('id'):
            category = Category.browse(self._id(data['id'])).exists()
            if not category:
                raise ValueError('Category not found.')
            category.write(vals)
        else:
            if Category.search_count([('name', '=ilike', vals['name'])]):
                raise ValueError('A category with this name already exists.')
            category = Category.create(vals)
        return {'category': {'id': category.id, 'name': category.name, 'active': category.active}}

    def _api_funds(self, staff, data):
        self._manager(staff)
        field = self._income_field()
        income = dict(self.env['church.give.transaction'].sudo()._read_group(
            self._income_domain(), ['fund_id'], [field + ':sum']))
        spent = dict(self.sudo()._read_group([('state', '=', 'paid')], ['fund_id'], ['amount_pkr:sum']))
        funds = self.env['church.give.fund'].sudo().search([])
        rows = []
        for fund in list(funds) + [self.env['church.give.fund']]:
            came_in, went_out = income.get(fund, 0.0), spent.get(fund, 0.0)
            if not fund and not came_in and not went_out:
                continue
            rows.append({'id': fund.id or None, 'name': fund.name or 'General (no fund)',
                         'type': fund.fund_type if fund else 'general', 'income': came_in,
                         'spent': went_out, 'balance': came_in - went_out,
                         'active': fund.is_active if fund else True})
        return {'funds': rows, 'note': 'Income is completed giving recorded in the app (PKR). '
                'Spending is paid expenses. Opening balances from before the app are not included.'}

    def _api_report(self, staff, data):
        self._manager(staff)
        today = self._today(staff)
        date_from = self._date(data.get('date_from'), today.replace(month=1, day=1))
        date_to = self._date(data.get('date_to'), today)
        if date_from > date_to:
            raise ValueError('The start date must be before the end date.')
        field = self._income_field()
        Tx = self.env['church.give.transaction'].sudo()
        domain = self._income_domain(date_from, date_to)
        income_by_category = [{'name': cat.name if cat else 'Other', 'amount': total}
            for cat, total in Tx._read_group(domain, ['category_id'], [field + ':sum'])]
        income_by_fund = [{'name': fund.name if fund else 'General (no fund)', 'amount': total}
            for fund, total in Tx._read_group(domain, ['fund_id'], [field + ':sum'])]
        paid_domain = [('state', '=', 'paid'), ('date', '>=', date_from), ('date', '<=', date_to)]
        spent_by_category = [{'name': cat.name, 'amount': total}
            for cat, total in self.sudo()._read_group(paid_domain, ['category_id'], ['amount_pkr:sum'])]
        income = sum(r['amount'] for r in income_by_category)
        spent = sum(r['amount'] for r in spent_by_category)
        return {'from': str(date_from), 'to': str(date_to), 'income': income, 'spent': spent,
                'net': income - spent, 'income_by_category': sorted(income_by_category, key=lambda r: -r['amount']),
                'income_by_fund': sorted(income_by_fund, key=lambda r: -r['amount']),
                'spent_by_category': sorted(spent_by_category, key=lambda r: -r['amount']),
                'budget': self._budget_lines(date_to.year) if date_from.year == date_to.year else [],
                'waiting': self._spent([('state', 'in', ['submitted', 'approved']),
                                        ('date', '>=', date_from), ('date', '<=', date_to)]),
                'prepared_by': staff.name, 'generated': str(fields.Datetime.now())}

    def _api_set_limit(self, staff, data):
        if staff.staff_role != 'admin':
            raise AccessError('Only an Admin can change the approval limit.')
        limit = rules.money(data.get('limit'))
        self.env['ir.config_parameter'].sudo().set_param(LIMIT_PARAM, str(limit))
        return {'approval_limit': float(limit)}


class ChurchExpenseLog(models.Model):
    _name = 'church.expense.log'
    _description = 'Church Expense History'
    _order = 'id'

    expense_id = fields.Many2one('church.expense', required=True, index=True, ondelete='cascade')
    staff_id = fields.Many2one('hr.employee', ondelete='set null')
    action = fields.Char(required=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('church_expense_internal'):
            raise AccessError('Expense history is written automatically.')
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError('Expense history cannot be changed.')


class ChurchBudget(models.Model):
    _name = 'church.budget'
    _description = 'Church Yearly Budget'
    _order = 'year desc'

    name = fields.Char(compute='_compute_name', store=True)
    year = fields.Integer(required=True, index=True)
    notes = fields.Text()
    line_ids = fields.One2many('church.budget.line', 'budget_id', string='Budget lines')
    total_planned = fields.Float(compute='_compute_total', digits=(16, 2))
    updated_by_id = fields.Many2one('hr.employee', readonly=True)

    _unique_year = models.Constraint('unique(year)', 'There is already a budget for this year.')

    @api.depends('year')
    def _compute_name(self):
        for budget in self:
            budget.name = 'Budget %s' % budget.year

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for budget in self:
            budget.total_planned = sum(budget.line_ids.mapped('amount'))

    @api.constrains('year')
    def _check_year(self):
        for budget in self:
            if not 2000 <= budget.year <= 2100:
                raise ValidationError('Choose a year between 2000 and 2100.')


class ChurchBudgetLine(models.Model):
    _name = 'church.budget.line'
    _description = 'Church Budget Line'
    _order = 'id'

    budget_id = fields.Many2one('church.budget', required=True, index=True, ondelete='cascade')
    category_id = fields.Many2one('church.expense.category', required=True, ondelete='restrict')
    amount = fields.Float(string='Planned (PKR)', digits=(16, 2))

    _unique_line = models.Constraint('unique(budget_id, category_id)',
        'Each category appears once in a budget.')

    @api.constrains('amount')
    def _check_amount(self):
        for line in self:
            if line.amount < 0:
                raise ValidationError('Budget amounts cannot be negative.')
