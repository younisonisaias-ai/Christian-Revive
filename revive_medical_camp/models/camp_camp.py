"""One medical camp, its team, budget and health-talk sessions."""
import re
import secrets
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

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
# Station switches on the Permissions tab: field -> right used by Camp Mode.
STATION_RIGHTS = {
    'can_registration': 'registration',
    'can_triage': 'nurse',
    'can_doctor': 'doctor',
    'can_pharmacy': 'pharmacist',
    'can_followup': 'followup',
    'can_talks': 'educator',
    'can_eye': 'eye',
}
# What each role can do until the coordinator changes the switches.
ROLE_DEFAULT_SWITCHES = {
    'coordinator': {'can_registration', 'can_followup', 'can_talks'},
    'registration': {'can_registration'},
    'nurse': {'can_registration', 'can_triage', 'can_eye'},
    'doctor': {'can_registration', 'can_triage', 'can_doctor', 'can_eye'},
    'pharmacist': {'can_pharmacy'},
    'educator': {'can_talks'},
    'followup': {'can_followup'},
    'helper': set(),
}


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
    closed_at = fields.Datetime(readonly=True, help='Doctors can correct finished visits until 7 days after this.')
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
        string='Remove patient data from staff devices after (days)', default=7,
        help='During the camp, Camp Mode keeps a copy of the patient data on the phones and tablets '
             'used by the camp staff, so they can work without internet. This many days after the camp '
             'date, that copy is deleted from those devices automatically (only once everything has '
             'been sent to the server).\n\n'
             'Nothing is deleted on the server: patient records, including their phone numbers, '
             'stay in Odoo for follow-up calls, returning patients and reports.')
    notes = fields.Html()
    token_reserved_upto = fields.Integer(
        readonly=True, copy=False,
        help='Highest token number handed out to camp phones in advance, so phones '
             'working offline never give two patients the same token.')

    team_member_ids = fields.One2many('camp.team.member', 'camp_id', string='Team')
    team_permission_ids = fields.One2many('camp.team.member', 'camp_id', string='Permissions')
    budget_line_ids = fields.One2many('camp.budget.line', 'camp_id', string='Budget')
    visit_ids = fields.One2many('camp.visit', 'camp_id', string='Visits')
    education_session_ids = fields.One2many('camp.education.session', 'camp_id', string='Health talks')

    # Totals (computed on read; never stored, so they always match the records)
    patients_seen = fields.Integer(compute='_compute_totals')
    referral_count = fields.Integer(compute='_compute_totals')
    flagged_count = fields.Integer(compute='_compute_totals')
    medicines_dispensed = fields.Float(compute='_compute_totals', string='Medicine units dispensed')
    budget_planned = fields.Float(compute='_compute_totals')
    budget_actual = fields.Float(compute='_compute_totals', string='Budget spent')
    medicines_value = fields.Float(
        compute='_compute_totals', string='Medicines given (value)',
        help='Medicines handed out, at their cost price in Inventory. Added to the total cost unless the budget '
             'already has a "Medicines" line with an amount spent.')
    total_cost = fields.Float(compute='_compute_totals', string='Total cost')
    cost_per_patient = fields.Float(compute='_compute_totals')
    currency_id = fields.Many2one(related='company_id.currency_id')
    team_count = fields.Integer(compute='_compute_totals')

    @api.depends('visit_ids.state', 'budget_line_ids.planned', 'budget_line_ids.actual', 'team_member_ids',
                 'visit_ids.prescription_line_ids.dispensed_qty')
    def _compute_totals(self):
        for camp in self:
            visits = camp.visit_ids.filtered(lambda v: v.state not in ('cancelled', 'booked'))
            camp.patients_seen = len(visits)
            camp.referral_count = len(visits.referral_ids)
            camp.flagged_count = len(visits.filtered('flag_rule_ids'))
            camp.medicines_dispensed = sum(visits.prescription_line_ids.mapped('dispensed_qty'))
            camp.budget_planned = sum(camp.budget_line_ids.mapped('planned'))
            camp.budget_actual = sum(camp.budget_line_ids.mapped('actual'))
            given = visits.sudo().prescription_line_ids.filtered(lambda l: l.dispensed_qty > 0)
            camp.medicines_value = sum(
                l.dispensed_qty * ((l.substitute_formulary_id or l.formulary_id).product_id.standard_price or 0)
                for l in given)
            in_budget = any(l.category == 'medicines' and l.actual for l in camp.budget_line_ids)
            camp.total_cost = camp.budget_actual + (0 if in_budget else camp.medicines_value)
            camp.cost_per_patient = camp.total_cost / len(visits) if visits else 0.0
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
            waiting = camp.visit_ids.filtered(
                lambda v: v.state in ('registered', 'triaged', 'with_doctor', 'at_pharmacy'))
            if waiting:
                raise UserError(_('%(count)s patients are still waiting (doctor or pharmacy). '
                                  'Finish or cancel their visits before closing the camp.',
                                  count=len(waiting)))
        self.write({'state': 'closed', 'closed_at': fields.Datetime.now()})

    def action_prepare_reminders(self):
        self.env['camp.reminder']._generate(self)
        return self.env['ir.actions.act_window']._for_xml_id('revive_medical_camp.action_camp_reminder') | {
            'domain': [('camp_id', 'in', self.ids)]}

    @api.model
    def _camp_report_logo(self):
        """The Christian Revive logo for every camp report, as a data URI."""
        import base64
        from odoo.tools.misc import file_open
        with file_open('revive_medical_camp/static/img/christian_revive_logo.png', 'rb') as f:
            return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()

    def action_stock_plan(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Stock plan'), 'res_model': 'camp.stock.plan',
                'view_mode': 'form', 'target': 'new', 'context': {'active_id': self.id}}

    def action_return_leftovers(self):
        """After the camp: a draft transfer of everything left back to the main store."""
        self.ensure_one()
        from ..wizard.camp_stock_plan import _main_stock
        warehouse = _main_stock(self)
        quants = self.env['stock.quant'].sudo().search([('location_id', 'child_of', self.stock_location_id.id),
                                                       ('quantity', '>', 0)])
        if not quants:
            raise UserError(_('Nothing is left at the camp.'))
        totals = {}
        for q in quants:
            totals[q.product_id] = totals.get(q.product_id, 0) + q.quantity
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': self.stock_location_id.id,
            'location_dest_id': warehouse.lot_stock_id.id,
            'origin': _('Return from %s', self.name),
            'move_ids': [(0, 0, {'product_id': p.id, 'product_uom_qty': qty, 'product_uom': p.uom_id.id,
                                 'location_id': self.stock_location_id.id,
                                 'location_dest_id': warehouse.lot_stock_id.id}) for p, qty in totals.items()],
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'stock.picking', 'res_id': picking.id,
                'view_mode': 'form', 'target': 'current'}

    def action_reopen(self):
        self.write({'state': 'running', 'closed_at': False})

    def _reserve_tokens(self, count=50):
        """Hand a block of token numbers to a phone for offline registration."""
        self.ensure_one()
        self.env.cr.execute('SELECT token_reserved_upto FROM camp_camp WHERE id = %s FOR UPDATE', (self.id,))
        reserved = self.env.cr.fetchone()[0] or 0
        self.env.cr.execute('SELECT COALESCE(MAX(token_no), 0) FROM camp_visit WHERE camp_id = %s', (self.id,))
        start = max(self.env.cr.fetchone()[0], reserved) + 1
        end = start + max(1, min(count, 500)) - 1
        self.env.cr.execute('UPDATE camp_camp SET token_reserved_upto = %s WHERE id = %s', (end, self.id))
        self.invalidate_recordset(['token_reserved_upto'])
        return {'from': start, 'to': end}

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
            'cost': self.total_cost,
            'medicines_value': self.medicines_value,
            'cost_per_patient': self.cost_per_patient,
            'min_group': min_group,
            'shortages': [(l.dispensed_product_id.display_name or l.product_id.display_name, l.shortage_qty)
                          for l in visits.prescription_line_ids if l.shortage_qty],
            'count_gaps': [(l.formulary_id.display_name, l.expected_qty, l.counted_qty, l.difference)
                           for l in self.env['camp.stock.count'].search(
                               [('camp_id', '=', self.id)], limit=1).line_ids if abs(l.difference) > 0.001],
            'followups_open': self.env['camp.followup'].search_count(
                [('camp_id', '=', self.id), ('state', 'in', ('to_call', 'no_answer'))]),
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
    email = fields.Char()
    role = fields.Selection(TEAM_ROLES, required=True, default='helper')
    # Permissions tab: which Camp Mode stations this person may use at this camp.
    can_registration = fields.Boolean('Registration', compute='_compute_switches', store=True, readonly=False)
    can_triage = fields.Boolean('Triage', compute='_compute_switches', store=True, readonly=False)
    can_doctor = fields.Boolean('Doctor', compute='_compute_switches', store=True, readonly=False,
                                help='Also needs a PMDC number before consultations are accepted.')
    can_pharmacy = fields.Boolean('Pharmacy', compute='_compute_switches', store=True, readonly=False)
    can_followup = fields.Boolean('Follow-up calls', compute='_compute_switches', store=True, readonly=False)
    can_talks = fields.Boolean('Health talks', compute='_compute_switches', store=True, readonly=False)
    can_eye = fields.Boolean('Eye check', compute='_compute_switches', store=True, readonly=False)
    # Shift at the camp, e.g. 8:00 to 14:00 (shown on the phone, sent in the day-before reminder).
    shift_start = fields.Float(help='Hour the shift starts, e.g. 8.0 for 8:00.')
    shift_end = fields.Float()
    pmdc_expiry = fields.Date(related='user_id.camp_pmdc_expiry', string='PMDC valid until')
    pmdc_warning = fields.Char(compute='_compute_pmdc_warning')
    login_type = fields.Selection([('portal', 'Free (portal)'), ('internal', 'Internal (paid)')],
                                  compute='_compute_login_type', string='Login type')
    pmdc_number = fields.Char(string='PMDC number', compute='_compute_pmdc_number',
                              inverse='_inverse_pmdc_number',
                              help='Doctors only. Saved on their login; needed before they can save a consultation.')
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

    @api.depends('role')
    def _compute_switches(self):
        """Choosing a role sets its usual stations; the coordinator can then
        switch any station on or off on the Permissions tab."""
        for member in self:
            on = ROLE_DEFAULT_SWITCHES.get(member.role, set())
            for field in STATION_RIGHTS:
                member[field] = field in on

    @api.depends('role', 'pmdc_expiry', 'camp_id.date_start')
    def _compute_pmdc_warning(self):
        for m in self:
            m.pmdc_warning = False
            if m.role != 'doctor' or not m.pmdc_expiry:
                continue
            day = m.camp_id.date_start or fields.Date.today()
            if m.pmdc_expiry < day:
                m.pmdc_warning = _('PMDC expired on %s', m.pmdc_expiry)
            elif (m.pmdc_expiry - day).days <= 30:
                m.pmdc_warning = _('PMDC expires on %s', m.pmdc_expiry)

    def _rights(self):
        """Camp Mode rights from the switches (see STATION_RIGHTS)."""
        return {right for member in self for field, right in STATION_RIGHTS.items() if member[field]}

    @api.depends('user_id')
    def _compute_login_type(self):
        for member in self:
            member.login_type = (('portal' if member.user_id.share else 'internal')
                                 if member.user_id else False)

    @api.depends('user_id')
    def _compute_pmdc_number(self):
        for member in self:
            member.pmdc_number = member.user_id.sudo().camp_pmdc_number

    def _inverse_pmdc_number(self):
        if not self.env.su and not self.env.user.has_group('revive_medical_camp.group_camp_coordinator'):
            raise AccessError(_('Only the camp coordinator can set PMDC numbers.'))
        for member in self.filtered('user_id'):
            member.user_id.sudo().camp_pmdc_number = member.pmdc_number

    def action_create_login(self):
        """Create a free portal login for a station worker (phone app only).

        The login is the email, or the phone number when there is no email.
        A password is generated and shown once to the coordinator."""
        self.ensure_one()
        if not self.env.user.has_group('revive_medical_camp.group_camp_coordinator'):
            raise AccessError(_('Only the camp coordinator can create camp logins.'))
        if self.user_id:
            raise UserError(_('%s already has a login.', self.name))
        email = (self.email or '').strip().lower()
        phone = re.sub(r'[^0-9+]', '', self.phone or '')
        if not (email or phone):
            raise UserError(_('Add an email or phone number first; it becomes the login.'))
        Users = self.env['res.users'].sudo().with_context(active_test=False, no_reset_password=True)
        login = email or phone
        existing = Users.search([('login', '=', login)], limit=1)
        if existing and not existing.share and phone:
            # The email already belongs to an office (paid) user: do not reuse
            # it; make a free login with the phone number. The email is still
            # saved, so the worker can also sign in with it.
            login = phone
            existing = Users.search([('login', '=', login)], limit=1)
        if existing and not existing.share:
            raise UserError(_('%(login)s is already used by an internal (paid) user. Add a phone number to '
                              'create a free login, or give that user a Medical Camps role instead.', login=login))
        if existing:
            self.user_id = existing
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _('Existing login linked'),
                'message': _('%(name)s already had the login %(login)s; it is now linked to this camp.',
                             name=self.name, login=login),
                'type': 'info', 'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}
        alphabet = 'abcdefghjkmnpqrstuvwxyz23456789'
        password = ''.join(secrets.choice(alphabet) for _i in range(10))
        user = Users.create({
            'name': self.name, 'login': login, 'email': email or False, 'phone': phone or False,
            'password': password,
            'group_ids': [(6, 0, [self.env.ref('base.group_portal').id])],
            'camp_must_change_password': True,
        })
        self.user_id = user
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('Camp login created'),
            'message': _('Login: %(login)s   Password: %(password)s\n'
                         'Give these to %(name)s privately. They sign in under Medical Camp Mode in the app '
                         'with this login%(also)s. This password is shown only once.',
                         login=login, password=password, name=self.name,
                         also=(_(' (or their email %s)', email) if email and email != login else '')),
            'sticky': True, 'type': 'success',
            # Refresh the camp so the Team line shows the new login straight away.
            'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'}}}

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
