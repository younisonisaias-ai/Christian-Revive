from odoo import api, fields, models


class CollegeFee(models.Model):
    _name = 'college.fee'
    _description = 'Bible College Fee / Tuition Charge'
    _order = 'due_date desc, id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    term_id = fields.Many2one('college.term')
    name = fields.Char(required=True, help='e.g. "Tuition Fall 2026"')
    amount = fields.Float(required=True)
    due_date = fields.Date()
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True)
    payment_ids = fields.One2many('college.payment', 'fee_id', string='Payments')
    amount_paid = fields.Float(compute='_compute_payment_state', store=True)
    amount_due = fields.Float(compute='_compute_payment_state', store=True)
    payment_state = fields.Selection([
        ('unpaid', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
    ], compute='_compute_payment_state', store=True)
    notes = fields.Text()

    @api.depends('amount', 'payment_ids.amount')
    def _compute_payment_state(self):
        for fee in self:
            paid = sum(fee.payment_ids.mapped('amount'))
            fee.amount_paid = paid
            fee.amount_due = fee.amount - paid
            if paid <= 0:
                fee.payment_state = 'unpaid'
            elif paid < fee.amount:
                fee.payment_state = 'partial'
            else:
                fee.payment_state = 'paid'

    def action_post(self):
        self.filtered(lambda f: f.state == 'draft').write({'state': 'posted'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})


class CollegePayment(models.Model):
    _name = 'college.payment'
    _description = 'Bible College Fee Payment'
    _order = 'date desc, id desc'

    fee_id = fields.Many2one('college.fee', required=True, ondelete='cascade')
    date = fields.Date(default=fields.Date.context_today, required=True)
    amount = fields.Float(required=True)
    method = fields.Selection([
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('card', 'Card'),
        ('other', 'Other'),
    ], default='cash', required=True)
    reference = fields.Char(string='Receipt / Reference')
    received_by = fields.Many2one('res.users', default=lambda self: self.env.user)
