"""Doctor's consultation, prescription lines and dispensing from camp stock."""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare


class CampConsultation(models.Model):
    _name = 'camp.consultation'
    _description = 'Camp Consultation'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True, index=True)
    doctor_id = fields.Many2one('res.users', string='Doctor', required=True, readonly=True,
                                default=lambda self: self.env.user, tracking=True)
    complaint = fields.Text(string='Chief complaint', tracking=True)
    history = fields.Text()
    examination = fields.Text()
    diagnosis_ids = fields.Many2many('camp.diagnosis.code', string='Diagnoses', tracking=True)
    advice = fields.Text()
    advice_ur = fields.Text(string='Advice (Urdu)')
    follow_up_needed = fields.Boolean(tracking=True)
    follow_up_reason = fields.Char()
    prescription_line_ids = fields.One2many('camp.prescription.line', 'consultation_id', string='Medicines')
    referral_ids = fields.One2many('camp.referral', 'consultation_id', string='Referrals')
    state = fields.Selection([('draft', 'In progress'), ('done', 'Finished')],
                             default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        self._check_is_doctor()
        records = super().create(vals_list)
        records.visit_id.filtered(lambda v: v.state in ('registered', 'triaged')).write({'state': 'with_doctor'})
        return records

    def write(self, vals):
        if set(vals) & {'diagnosis_ids', 'prescription_line_ids', 'complaint', 'examination'}:
            self._check_is_doctor()
        return super().write(vals)

    def _check_is_doctor(self):
        """Only a doctor with a PMDC number may save a diagnosis or prescription."""
        if self.env.su:
            return
        user = self.env.user
        if not user.has_group('revive_medical_camp.group_camp_doctor'):
            raise AccessError(_('Only camp doctors can save consultations.'))
        if not user.camp_pmdc_number:
            raise ValidationError(_('Add your PMDC number to your user profile before saving a consultation.'))

    def action_finish(self):
        """Doctor is done: the patient goes to the pharmacy if medicines were given."""
        for c in self:
            c.state = 'done'
            if c.prescription_line_ids.filtered(lambda l: l.state == 'prescribed'):
                c.visit_id.state = 'at_pharmacy'
            else:
                c.visit_id.action_done()

    def action_print_slip(self):
        return self.env.ref('revive_medical_camp.action_report_prescription_slip').report_action(self)


class CampPrescriptionLine(models.Model):
    _name = 'camp.prescription.line'
    _description = 'Prescription Line'
    _inherit = ['camp.sync.mixin']
    _order = 'consultation_id, sequence, id'

    sequence = fields.Integer(default=10)
    consultation_id = fields.Many2one('camp.consultation', required=True, ondelete='cascade', index=True)
    visit_id = fields.Many2one(related='consultation_id.visit_id', store=True, index=True)
    camp_id = fields.Many2one(related='consultation_id.camp_id', store=True, index=True)
    formulary_id = fields.Many2one('camp.formulary', string='Medicine', required=True, ondelete='restrict',
                                   help='Only medicines in the camp formulary can be prescribed.')
    product_id = fields.Many2one(related='formulary_id.product_id', store=True, string='Product')
    dose_template_id = fields.Many2one('camp.dose.template', string='Dose',
                                       compute='_compute_defaults', store=True, readonly=False)
    days = fields.Integer(compute='_compute_defaults', store=True, readonly=False)
    quantity = fields.Float(compute='_compute_quantity', store=True, readonly=False,
                            help='Units to give (worked out from the dose and days; can be changed).')
    instructions_ur = fields.Char(string='Instructions (Urdu)', compute='_compute_defaults',
                                  store=True, readonly=False)
    available_qty = fields.Float(string='In camp stock', compute='_compute_available_qty')

    state = fields.Selection([
        ('prescribed', 'To dispense'),
        ('dispensed', 'Dispensed'),
        ('partial', 'Partly dispensed'),
        ('not_given', 'Not given'),
    ], default='prescribed', required=True, index=True)
    dispensed_qty = fields.Float(readonly=True)
    substitute_formulary_id = fields.Many2one('camp.formulary', string='Substitute given')
    dispensed_product_id = fields.Many2one('product.product', readonly=True)
    substitution_reason = fields.Char(string='Reason (substitute / partial / not given)')
    lot_ids = fields.Many2many('stock.lot', string='Batches given', readonly=True)
    move_ids = fields.Many2many('stock.move', string='Stock moves', readonly=True, copy=False)
    shortage_qty = fields.Float(
        readonly=True,
        help='Recorded as given on an offline phone, but the camp stock did not have it. '
             'Check during stock reconciliation.')
    dispensed_by_id = fields.Many2one('res.users', readonly=True)
    dispensed_at = fields.Datetime(readonly=True)

    @api.depends('formulary_id')
    def _compute_defaults(self):
        for line in self:
            f = line.formulary_id
            if not line.dose_template_id:
                line.dose_template_id = f.default_dose_template_id
            if not line.days:
                line.days = f.default_days or 1
            if not line.instructions_ur:
                line.instructions_ur = f.instructions_ur

    @api.depends('dose_template_id', 'days')
    def _compute_quantity(self):
        for line in self:
            per_day = line.dose_template_id.doses_per_day or 1
            line.quantity = per_day * (line.days or 1)

    @api.depends('product_id', 'camp_id.stock_location_id')
    def _compute_available_qty(self):
        for line in self:
            loc = line.camp_id.stock_location_id
            line.available_qty = line.product_id.with_context(location=loc.id).qty_available \
                if loc and line.product_id else 0.0

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('Quantity must be more than zero.'))

    # ── Dispensing ─────────────────────────────────────────────
    def action_dispense(self, quantity=None, substitute_formulary_id=None, reason=None,
                        allow_shortage=False):
        """Give the medicine from the camp's stock location.

        Batches with the nearest expiry go first and expired batches are never
        used. ``allow_shortage`` is for records synced from an offline phone:
        whatever the stock cannot cover is recorded in ``shortage_qty`` for
        reconciliation instead of failing the upload."""
        for line in self:
            if line.state != 'prescribed':
                raise UserError(_('%s was already handled at the pharmacy.', line.formulary_id.display_name))
            location = line.camp_id.stock_location_id
            if not location:
                raise UserError(_('Set a medicine stock location on camp %s first.', line.camp_id.name))
            formulary = self.env['camp.formulary'].browse(substitute_formulary_id) \
                if substitute_formulary_id else line.formulary_id
            if formulary != line.formulary_id and not reason:
                raise UserError(_('Give a reason for the substitute medicine.'))
            wanted = line.quantity if quantity is None else quantity
            if float_compare(wanted, line.quantity, precision_digits=3) < 0 and not reason:
                raise UserError(_('Give a reason for giving less than prescribed.'))

            product = formulary.product_id
            allocations, available = line._allocate_stock(product, location, wanted)
            given = min(wanted, available)
            if float_compare(given, wanted, precision_digits=3) < 0 and not allow_shortage:
                raise UserError(_('Only %(have)s of %(med)s left in camp stock (expired batches are not counted).',
                                  have=available, med=formulary.display_name))
            moves = line._create_moves(product, location, allocations) if given else self.env['stock.move']
            line.write({
                'dispensed_qty': wanted if allow_shortage else given,
                'shortage_qty': max(0.0, wanted - given) if allow_shortage else 0.0,
                'dispensed_product_id': product.id,
                'substitute_formulary_id': formulary.id if formulary != line.formulary_id else False,
                'substitution_reason': reason or line.substitution_reason,
                'lot_ids': [(6, 0, [lot.id for lot, _q, _loc in allocations if lot])],
                'move_ids': [(4, m.id) for m in moves],
                'state': 'dispensed' if float_compare(wanted, line.quantity, precision_digits=3) >= 0 else 'partial',
                'dispensed_by_id': self.env.user.id,
                'dispensed_at': fields.Datetime.now(),
            })
        self._close_finished_visits()
        return True

    def action_not_given(self, reason=None):
        if not reason:
            raise UserError(_('Give a reason why the medicine was not given.'))
        self.filtered(lambda l: l.state == 'prescribed').write({
            'state': 'not_given', 'substitution_reason': reason,
            'dispensed_by_id': self.env.user.id, 'dispensed_at': fields.Datetime.now(),
        })
        self._close_finished_visits()
        return True

    def action_dispense_button(self):
        """Form button: dispense the full prescribed quantity."""
        return self.action_dispense()

    def _allocate_stock(self, product, location, wanted):
        """[(lot, qty, quant location)], nearest expiry first, skipping expired lots."""
        now = fields.Datetime.now()
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('quantity', '>', 0),
        ])
        usable = quants.filtered(lambda q: not (q.lot_id and q.lot_id.expiration_date
                                                and q.lot_id.expiration_date <= now))
        usable = usable.sorted(lambda q: (q.lot_id.expiration_date or fields.Datetime.to_datetime('2999-12-31'),
                                          q.in_date or now))
        allocations, remaining, available = [], wanted, 0.0
        for quant in usable:
            free = quant.quantity - quant.reserved_quantity
            if free <= 0:
                continue
            available += free
            if remaining > 0:
                take = min(free, remaining)
                allocations.append((quant.lot_id, take, quant.location_id))
                remaining -= take
        return allocations, available

    def _create_moves(self, product, location, allocations):
        self.ensure_one()
        customers = self.env.ref('stock.stock_location_customers')
        total = sum(q for _lot, q, _loc in allocations)
        Move = self.env['stock.move'].sudo()
        move = Move.create({
            'product_id': product.id,
            'product_uom_qty': total,
            'product_uom': product.uom_id.id,
            'location_id': location.id,
            'location_dest_id': customers.id,
            'company_id': self.camp_id.company_id.id,
            'origin': f'{self.camp_id.name} / {self.visit_id.display_name}',
        })
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].sudo().create([{
            'move_id': move.id,
            'product_id': product.id,
            'product_uom_id': product.uom_id.id,
            'lot_id': lot.id if lot else False,
            'quantity': qty,
            'location_id': quant_location.id,
            'location_dest_id': customers.id,
        } for lot, qty, quant_location in allocations])
        move.picked = True
        move._action_done()
        return move

    def _close_finished_visits(self):
        for visit in self.visit_id:
            pending = visit.prescription_line_ids.filtered(lambda l: l.state == 'prescribed')
            if not pending and visit.state == 'at_pharmacy':
                visit.action_done()
