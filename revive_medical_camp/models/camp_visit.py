"""A patient's visit to one camp (token, station, priority) and the triage
vitals that raise red flags."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .camp_config import PRIORITIES

VISIT_STATES = [
    ('registered', 'Registered'),
    ('triaged', 'Triaged'),
    ('with_doctor', 'With doctor'),
    ('at_pharmacy', 'At pharmacy'),
    ('done', 'Done'),
    ('referred', 'Referred'),
    ('cancelled', 'Cancelled'),
]
PRIORITY_RANK = {'normal': 0, 'high': 1, 'urgent': 2}


class CampVisit(models.Model):
    _name = 'camp.visit'
    _description = 'Camp Visit'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'priority_rank desc, token_no'
    _rec_names_search = ['patient_id', 'qr_code']

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='restrict', index=True, tracking=True)
    patient_id = fields.Many2one('camp.patient', required=True, ondelete='restrict', index=True)
    token_no = fields.Integer(string='Token', readonly=True, copy=False, index=True)
    qr_code = fields.Char(string='QR code', compute='_compute_qr_code', store=True, index=True,
                          help='Printed on the patient card; stations scan it instead of searching.')
    arrived_at = fields.Datetime(default=fields.Datetime.now)
    state = fields.Selection(VISIT_STATES, default='registered', required=True, tracking=True, index=True)
    priority = fields.Selection(PRIORITIES, default='normal', required=True, tracking=True)
    priority_rank = fields.Integer(compute='_compute_priority_rank', store=True)
    consent_signature = fields.Binary(string='Consent signature', attachment=True)
    consent_confirmed = fields.Boolean(
        string='Consent confirmed',
        help='Care & records consent was explained and given for this visit. Required before triage.')
    is_first_visit = fields.Boolean(compute='_compute_is_first_visit', store=True)

    # Patient details shown on queues (read from the patient)
    patient_name = fields.Char(related='patient_id.name')
    patient_age = fields.Integer(related='patient_id.age_years')
    patient_sex = fields.Selection(related='patient_id.sex')
    patient_area = fields.Char(related='patient_id.area')

    vitals_ids = fields.One2many('camp.vitals', 'visit_id', string='Vitals')
    consultation_ids = fields.One2many('camp.consultation', 'visit_id', string='Consultations')
    prescription_line_ids = fields.One2many('camp.prescription.line', 'visit_id', string='Medicines')
    referral_ids = fields.One2many('camp.referral', 'visit_id', string='Referrals')
    flag_rule_ids = fields.Many2many('camp.flag.rule', compute='_compute_flags', store=True,
                                     string='Red flags')

    _token_unique = models.Constraint('UNIQUE(camp_id, token_no)', 'Token numbers must be unique in a camp.')
    _patient_once = models.Constraint('UNIQUE(camp_id, patient_id)',
                                      'This patient is already registered at this camp.')

    @api.depends('camp_id', 'token_no', 'patient_id.patient_code')
    def _compute_qr_code(self):
        for v in self:
            v.qr_code = f'CAMP1:{v.camp_id.id}:{v.token_no}:{v.patient_id.patient_code or ""}' if v.token_no else False

    @api.depends('priority')
    def _compute_priority_rank(self):
        for v in self:
            v.priority_rank = PRIORITY_RANK.get(v.priority, 0)

    @api.depends('patient_id', 'camp_id')
    def _compute_is_first_visit(self):
        for v in self:
            earlier = self.search_count([
                ('patient_id', '=', v.patient_id.id), ('id', '!=', v.id or 0),
                ('camp_id.date_start', '<', v.camp_id.date_start),
            ]) if v.patient_id and v.camp_id else 0
            v.is_first_visit = not earlier

    @api.depends('vitals_ids.flag_rule_ids')
    def _compute_flags(self):
        for v in self:
            v.flag_rule_ids = v.vitals_ids.flag_rule_ids

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('token_no') and vals.get('camp_id'):
                vals['token_no'] = self._next_token(vals['camp_id'])
        visits = super().create(vals_list)
        for v in visits:
            if v.camp_id.state == 'closed':
                raise UserError(_('Camp "%s" is closed; new patients cannot be registered.', v.camp_id.name))
        return visits

    def _next_token(self, camp_id):
        # Lock the camp row so two registration desks never get the same token.
        self.env.cr.execute('SELECT id FROM camp_camp WHERE id = %s FOR UPDATE', (camp_id,))
        self.env.cr.execute('SELECT COALESCE(MAX(token_no), 0) FROM camp_visit WHERE camp_id = %s', (camp_id,))
        return self.env.cr.fetchone()[0] + 1

    def _apply_flag_priority(self):
        """Red flags move the patient up the doctor's queue (never down)."""
        for v in self:
            flagged = max((PRIORITY_RANK[r.priority] for r in v.flag_rule_ids), default=0)
            if flagged > PRIORITY_RANK.get(v.priority, 0):
                v.priority = next(k for k, rank in PRIORITY_RANK.items() if rank == flagged)

    @api.depends('patient_id', 'token_no')
    def _compute_display_name(self):
        for v in self:
            v.display_name = f'#{v.token_no} {v.patient_id.name or ""}'.strip()

    # ── Station buttons ────────────────────────────────────────
    def action_send_to_doctor(self):
        self.filtered(lambda v: v.state in ('registered', 'triaged')).write({'state': 'triaged'})

    def action_done(self):
        for v in self:
            v.state = 'referred' if v.referral_ids else 'done'

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_print_card(self):
        return self.env.ref('revive_medical_camp.action_report_patient_card').report_action(self)


class CampVitals(models.Model):
    _name = 'camp.vitals'
    _description = 'Triage Vitals'
    _inherit = ['camp.sync.mixin']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    taken_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    bp_systolic = fields.Integer(string='BP systolic')
    bp_diastolic = fields.Integer(string='BP diastolic')
    pulse = fields.Integer()
    temperature = fields.Float(digits=(4, 1), help='°C')
    spo2 = fields.Integer(string='SpO2 %')
    weight = fields.Float(digits=(5, 1), help='kg')
    height = fields.Float(digits=(5, 1), help='cm')
    bmi = fields.Float(string='BMI', digits=(4, 1), compute='_compute_bmi', store=True)
    blood_sugar = fields.Integer(string='Blood sugar', help='Random, mg/dL')
    hemoglobin = fields.Float(string='Haemoglobin', digits=(4, 1), help='g/dL')
    urine_dipstick = fields.Char(string='Urine dipstick')
    vision_left = fields.Char(string='Vision (left)', help='e.g. 6/9')
    vision_right = fields.Char(string='Vision (right)')
    notes = fields.Char()
    flag_rule_ids = fields.Many2many('camp.flag.rule', compute='_compute_flags', store=True,
                                     string='Red flags')

    @api.depends('weight', 'height')
    def _compute_bmi(self):
        for r in self:
            r.bmi = r.weight / ((r.height / 100) ** 2) if r.weight and r.height else 0.0

    @api.depends('bp_systolic', 'bp_diastolic', 'pulse', 'temperature', 'spo2', 'bmi',
                 'blood_sugar', 'hemoglobin')
    def _compute_flags(self):
        rules = self.env['camp.flag.rule'].sudo().search([])
        for r in self:
            r.flag_rule_ids = rules.filtered(lambda rule: rule.matches(r))

    @api.constrains('visit_id')
    def _check_consent(self):
        for r in self:
            if not (r.visit_id.consent_confirmed or r.visit_id.patient_id.consent_care):
                raise ValidationError(_('Care & records consent is needed before triage for %s.',
                                        r.visit_id.patient_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._after_save()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._after_save()
        return result

    def _after_save(self):
        visits = self.visit_id
        visits.filtered(lambda v: v.state == 'registered').write({'state': 'triaged'})
        visits._apply_flag_priority()
