"""After the camp: follow-up calls for referred and flagged patients, and the
pharmacist's end-of-camp stock count."""
from datetime import timedelta

from odoo import _, api, fields, models

FOLLOWUP_KINDS = [
    ('referral', 'Referred to hospital'),
    ('doctor', 'Doctor asked for follow-up'),
    ('red_flag', 'Urgent red flag'),
]


class CampFollowup(models.Model):
    _name = 'camp.followup'
    _description = 'Follow-up Call'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'state_rank, due_date, id'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True)
    patient_phone = fields.Char(related='patient_id.phone')
    referral_id = fields.Many2one('camp.referral', ondelete='set null')
    kind = fields.Selection(FOLLOWUP_KINDS, required=True, default='doctor')
    reason = fields.Char(required=True)
    due_date = fields.Date(default=lambda self: fields.Date.context_today(self) + timedelta(days=3), index=True)
    assigned_to_id = fields.Many2one('res.users', string='Assigned to', tracking=True)
    state = fields.Selection([
        ('to_call', 'To call'),
        ('no_answer', 'No answer — try again'),
        ('reached', 'Reached'),
        ('closed', 'Closed'),
    ], default='to_call', required=True, tracking=True, index=True)
    state_rank = fields.Integer(compute='_compute_state_rank', store=True)
    call_count = fields.Integer(readonly=True)
    last_call_at = fields.Datetime(readonly=True)
    outcome = fields.Text(tracking=True)

    _visit_kind_unique = models.Constraint('UNIQUE(visit_id, kind, referral_id)',
                                           'This follow-up already exists.')

    @api.depends('state')
    def _compute_state_rank(self):
        rank = {'no_answer': 0, 'to_call': 1, 'reached': 2, 'closed': 3}
        for f in self:
            f.state_rank = rank.get(f.state, 9)

    @api.depends('patient_id', 'reason')
    def _compute_display_name(self):
        for f in self:
            f.display_name = f'{f.patient_id.name or ""}: {f.reason or ""}'

    @api.model
    def _ensure(self, visit, kind, reason, referral=None, days=3):
        """Create the follow-up once (safe to call repeatedly)."""
        domain = [('visit_id', '=', visit.id), ('kind', '=', kind),
                  ('referral_id', '=', referral.id if referral else False)]
        existing = self.sudo().search(domain, limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'visit_id': visit.id, 'kind': kind, 'reason': reason or kind,
            'referral_id': referral.id if referral else False,
            'due_date': fields.Date.context_today(self) + timedelta(days=days),
        })

    def log_call(self, result, notes=None, outcome=None, referral_attended=False):
        """One phone call: result is reached / no_answer / closed."""
        if result not in ('reached', 'no_answer', 'closed'):
            raise ValueError(_('Unknown call result: %s', result))
        for f in self:
            vals = {'state': result, 'call_count': f.call_count + 1, 'last_call_at': fields.Datetime.now()}
            if outcome:
                vals['outcome'] = outcome
            f.write(vals)
            if notes:
                f.message_post(body=notes)
            if referral_attended and f.referral_id and f.referral_id.status == 'issued':
                f.referral_id.sudo().write({'status': 'attended', 'outcome': outcome or f.referral_id.outcome})
        return True

    def action_reached(self):
        return self.log_call('reached')

    def action_no_answer(self):
        return self.log_call('no_answer')

    def action_close(self):
        return self.log_call('closed')


class CampStockCount(models.Model):
    _name = 'camp.stock.count'
    _description = 'Camp Stock Count'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'counted_at desc, id desc'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True)
    counted_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    counted_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    notes = fields.Text()
    line_ids = fields.One2many('camp.stock.count.line', 'count_id', string='Medicines')
    difference_count = fields.Integer(compute='_compute_difference_count', string='Medicines that differ')

    @api.depends('line_ids.difference')
    def _compute_difference_count(self):
        for c in self:
            c.difference_count = len(c.line_ids.filtered(lambda l: abs(l.difference) > 0.001))

    @api.depends('camp_id', 'counted_at')
    def _compute_display_name(self):
        for c in self:
            c.display_name = _('Stock count %(camp)s %(date)s', camp=c.camp_id.name or '',
                               date=fields.Datetime.to_string(c.counted_at)[:16] if c.counted_at else '')


class CampStockCountLine(models.Model):
    _name = 'camp.stock.count.line'
    _description = 'Camp Stock Count Line'
    _order = 'difference, id'

    count_id = fields.Many2one('camp.stock.count', required=True, ondelete='cascade', index=True)
    formulary_id = fields.Many2one('camp.formulary', string='Medicine', required=True, ondelete='restrict')
    expected_qty = fields.Float(string='Expected (system)', readonly=True,
                                help='Units in the camp stock location when the count arrived, all batches.')
    counted_qty = fields.Float(string='Counted')
    difference = fields.Float(compute='_compute_difference', store=True,
                              help='Counted minus expected: negative means units are missing.')

    @api.depends('expected_qty', 'counted_qty')
    def _compute_difference(self):
        for l in self:
            l.difference = l.counted_qty - l.expected_qty
