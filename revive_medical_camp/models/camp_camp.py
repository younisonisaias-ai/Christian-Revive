"""One medical camp, its team, budget and health-talk sessions."""
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError

AGE_BANDS = [(0, 4, '0-4'), (5, 14, '5-14'), (15, 49, '15-49'), (50, 200, '50+')]
TEAM_ROLES = [
    ('coordinator', 'Coordinator'),
    ('registration', 'Registration'),
    ('nurse', 'Nurse'),
    ('doctor', 'Doctor'),
    ('pharmacist', 'Pharmacist'),
    ('educator', 'Health educator'),
    ('followup', 'Follow-up'),
    ('helper', 'Helper'),
]


class CampCamp(models.Model):
    _name = 'camp.camp'
    _description = 'Medical Camp'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(required=True, tracking=True)
    date_start = fields.Date(string='Date', required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(string='End date', help='Leave empty for a one-day camp.')
    site = fields.Char(help='Venue, e.g. "Community hall, Youhanabad"')
    area = fields.Char(index=True, help='Town / district, used in area reports.')
    local_partner_id = fields.Many2one('res.partner', string='Local partner')
    sponsor_ids = fields.Many2many('res.partner', 'camp_camp_sponsor_rel', 'camp_id', 'partner_id',
                                   string='Sponsors')
    speciality_ids = fields.Many2many('camp.speciality', string='Specialities')
    expected_patients = fields.Integer()
    coordinator_id = fields.Many2one('res.users', string='Coordinator', default=lambda self: self.env.user)
    state = fields.Selection([
        ('draft', 'Planning'),
        ('ready', 'Ready'),
        ('running', 'Running'),
        ('closed', 'Closed'),
    ], default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)
    stock_location_id = fields.Many2one(
        'stock.location', string='Medicine stock location', domain=[('usage', '=', 'internal')],
        help='Medicines for this camp are moved here before the camp and dispensed from here.')
    device_purge_days = fields.Integer(
        string='Clear phones after (days)', default=7,
        help='Patient data saved on camp phones is deleted this many days after the camp closes.')
    notes = fields.Html()

    team_member_ids = fields.One2many('camp.team.member', 'camp_id', string='Team')
    budget_line_ids = fields.One2many('camp.budget.line', 'camp_id', string='Budget')
    visit_ids = fields.One2many('camp.visit', 'camp_id', string='Visits')
    education_session_ids = fields.One2many('camp.education.session', 'camp_id', string='Health talks')

    # Totals (computed on read; never stored, so they always match the records)
    patients_seen = fields.Integer(compute='_compute_totals')
    referral_count = fields.Integer(compute='_compute_totals')
    flagged_count = fields.Integer(compute='_compute_totals')
    medicines_dispensed = fields.Float(compute='_compute_totals', string='Medicine units dispensed')
    budget_planned = fields.Float(compute='_compute_totals')
    budget_actual = fields.Float(compute='_compute_totals', string='Total cost')
    cost_per_patient = fields.Float(compute='_compute_totals')
    team_count = fields.Integer(compute='_compute_totals')

    @api.depends('visit_ids.state', 'budget_line_ids.planned', 'budget_line_ids.actual', 'team_member_ids')
    def _compute_totals(self):
        for camp in self:
            visits = camp.visit_ids.filtered(lambda v: v.state != 'cancelled')
            camp.patients_seen = len(visits)
            camp.referral_count = len(visits.referral_ids)
            camp.flagged_count = len(visits.filtered('flag_rule_ids'))
            camp.medicines_dispensed = sum(visits.prescription_line_ids.mapped('dispensed_qty'))
            camp.budget_planned = sum(camp.budget_line_ids.mapped('planned'))
            camp.budget_actual = sum(camp.budget_line_ids.mapped('actual'))
            camp.cost_per_patient = camp.budget_actual / len(visits) if visits else 0.0
            camp.team_count = len(camp.team_member_ids)

    # ── Stock location ───────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        camps = super().create(vals_list)
        for camp in camps.filtered(lambda c: not c.stock_location_id):
            camp.stock_location_id = camp._create_stock_location()
        return camps

    def _create_stock_location(self):
        self.ensure_one()
        warehouse = self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', self.company_id.id)], limit=1)
        if not warehouse:
            return False
        parent = self.env['stock.location'].sudo().search([
            ('name', '=', 'Medical Camps'), ('location_id', '=', warehouse.lot_stock_id.id),
        ], limit=1) or self.env['stock.location'].sudo().create({
            'name': 'Medical Camps', 'usage': 'view', 'location_id': warehouse.lot_stock_id.id,
        })
        return self.env['stock.location'].sudo().create({
            'name': self.name, 'usage': 'internal', 'location_id': parent.id,
            'company_id': self.company_id.id,
        })

    # ── State buttons ───────────────────────────────────────────
    def action_ready(self):
        self.write({'state': 'ready'})

    def action_start(self):
        self.write({'state': 'running'})

    def action_close(self):
        for camp in self:
            waiting = camp.visit_ids.filtered(lambda v: v.state in ('registered', 'triaged', 'with_doctor'))
            if waiting:
                raise UserError(_('%(count)s patients are still waiting (not seen by a doctor). '
                                  'Finish or cancel their visits before closing the camp.',
                                  count=len(waiting)))
        self.write({'state': 'closed'})

    def action_reopen(self):
        self.write({'state': 'running'})

    # ── Report data ─────────────────────────────────────────────
    def _report_stats(self, min_group=1):
        """Totals for the summary (min_group=1) and sponsor report (min_group=5).

        Any count below min_group is returned as None, so a small group in a
        village can never point to one person in a sponsor report."""
        self.ensure_one()
        # Totals only (no clinical notes leave this method), so coordinators
        # can print reports without reading individual consultations.
        self = self.sudo()  # noqa: PLW0642
        visits = self.visit_ids.filtered(lambda v: v.state != 'cancelled')
        def hide(n):
            """0 stays 0; a small group (1..min_group-1) becomes None ("<5")."""
            return n if n == 0 or n >= min_group else None

        bands = Counter()
        for v in visits:
            age = v.patient_id.age_years
            label = next((b[2] for b in AGE_BANDS if b[0] <= age <= b[1]), 'Unknown')
            bands[(label, v.patient_id.sex or 'unknown')] += 1
        age_rows = []
        for low, high, label in AGE_BANDS + [(None, None, 'Unknown')]:
            row = {'band': label}
            for sex in ('male', 'female', 'other', 'unknown'):
                row[sex] = hide(bands[(label, sex)])
            total = sum(bands[(label, s)] for s in ('male', 'female', 'other', 'unknown'))
            if total:
                row['total'] = hide(total)
                age_rows.append(row)

        diagnoses = Counter()
        for c in visits.consultation_ids:
            for d in c.diagnosis_ids:
                diagnoses[d.display_name] += 1
        top_diagnoses = [(name, n) for name, n in diagnoses.most_common(10) if hide(n) is not None]

        medicines = Counter()
        for line in visits.prescription_line_ids.filtered('dispensed_qty'):
            product = line.dispensed_product_id or line.product_id
            medicines[product.display_name] += line.dispensed_qty
        flags = Counter(r.name for v in visits for r in v.flag_rule_ids)

        return {
            'patients': len(visits),
            'new_patients': len(visits.filtered(lambda v: v.is_first_visit)),
            'male': hide(len(visits.filtered(lambda v: v.patient_id.sex == 'male'))),
            'female': hide(len(visits.filtered(lambda v: v.patient_id.sex == 'female'))),
            'age_rows': age_rows,
            'top_diagnoses': top_diagnoses,
            'medicines': sorted(medicines.items(), key=lambda kv: -kv[1]),
            'flags': [(name, n) for name, n in flags.most_common() if hide(n) is not None],
            'referrals': hide(len(visits.referral_ids)),
            'talks': [(s.topic, s.attendees_count) for s in self.education_session_ids],
            'talk_attendees': sum(self.education_session_ids.mapped('attendees_count')),
            'team': len(self.team_member_ids),
            'team_hours': round(sum(self.team_member_ids.mapped('hours')), 1),
            'cost': self.budget_actual,
            'cost_per_patient': self.cost_per_patient,
            'min_group': min_group,
        }


class CampTeamMember(models.Model):
    _name = 'camp.team.member'
    _description = 'Camp Team Member'
    _inherit = ['camp.sync.mixin']
    _order = 'role, name'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='App login',
                              help='The person\'s own login; gives them this camp in Camp Mode.')
    name = fields.Char(required=True)
    phone = fields.Char()
    role = fields.Selection(TEAM_ROLES, required=True, default='helper')
    checked_in_at = fields.Datetime(string='Checked in')
    checked_out_at = fields.Datetime(string='Checked out')
    hours = fields.Float(compute='_compute_hours', store=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') and vals.get('user_id'):
                vals['name'] = self.env['res.users'].browse(vals['user_id']).name
        return super().create(vals_list)

    @api.onchange('user_id')
    def _onchange_user_id(self):
        if self.user_id and not self.name:
            self.name = self.user_id.name

    @api.depends('checked_in_at', 'checked_out_at')
    def _compute_hours(self):
        for member in self:
            if member.checked_in_at and member.checked_out_at:
                member.hours = max(0.0, (member.checked_out_at - member.checked_in_at).total_seconds() / 3600)
            else:
                member.hours = 0.0

    def action_check_in(self):
        self.write({'checked_in_at': fields.Datetime.now(), 'checked_out_at': False})

    def action_check_out(self):
        self.write({'checked_out_at': fields.Datetime.now()})


class CampBudgetLine(models.Model):
    _name = 'camp.budget.line'
    _description = 'Camp Budget Line'
    _order = 'category, id'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True)
    category = fields.Selection([
        ('medicines', 'Medicines'), ('supplies', 'Medical supplies'), ('transport', 'Transport'),
        ('food', 'Food & refreshments'), ('venue', 'Venue & tents'), ('staff', 'Staff / honoraria'),
        ('printing', 'Printing & banners'), ('other', 'Other'),
    ], required=True, default='other')
    description = fields.Char()
    planned = fields.Float()
    actual = fields.Float(help='Filled in after the camp.')
    currency_id = fields.Many2one(related='camp_id.company_id.currency_id')


class CampEducationSession(models.Model):
    _name = 'camp.education.session'
    _description = 'Health Talk'
    _inherit = ['camp.sync.mixin']
    _order = 'start_time desc, id desc'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True)
    topic = fields.Char(required=True, help='e.g. Hand washing, Diabetes care, Clean water')
    educator = fields.Char()
    start_time = fields.Datetime(default=fields.Datetime.now)
    attendees_count = fields.Integer(string='Attendees')
