"""More care at the camp: eye checks and glasses, clinical photos (with the
patient's consent), pregnancy checks and children's vaccines."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

EYE_FINDINGS = [
    ('cataract', 'Cataract'),
    ('pterygium', 'Pterygium'),
    ('red_eye', 'Red / infected eye'),
    ('glaucoma', 'Glaucoma suspected'),
    ('diabetic', 'Diabetic eye changes'),
    ('squint', 'Squint'),
]
ANC_DANGER_SIGNS = [
    ('bleeding', 'Vaginal bleeding'),
    ('headache', 'Severe headache / blurred vision'),
    ('fits', 'Fits (convulsions)'),
    ('swelling', 'Swelling of face or hands'),
    ('fever', 'High fever'),
    ('less_movement', 'Baby moving less'),
    ('pain', 'Severe belly pain'),
    ('breathless', 'Short of breath'),
]
# Pakistan EPI schedule: (vaccine, label, due at age in weeks)
VACCINES = [
    ('bcg', 'BCG', 0), ('opv0', 'OPV-0', 0), ('hepb0', 'Hepatitis B (birth)', 0),
    ('opv1', 'OPV-1', 6), ('penta1', 'Penta-1', 6), ('pcv1', 'PCV-1', 6), ('rota1', 'Rota-1', 6),
    ('opv2', 'OPV-2', 10), ('penta2', 'Penta-2', 10), ('pcv2', 'PCV-2', 10), ('rota2', 'Rota-2', 10),
    ('opv3', 'OPV-3', 14), ('penta3', 'Penta-3', 14), ('pcv3', 'PCV-3', 14), ('ipv', 'IPV', 14),
    ('mr1', 'Measles-Rubella 1', 39), ('tcv', 'Typhoid (TCV)', 39), ('mr2', 'Measles-Rubella 2', 65),
]


class CampGlasses(models.Model):
    """Ready-made glasses at the camp, counted by power."""
    _name = 'camp.glasses'
    _description = 'Camp Glasses Stock'
    _order = 'camp_id, kind, power'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('reading', 'Reading'), ('distance', 'Distance')], required=True, default='reading')
    power = fields.Float(required=True, digits=(4, 2), help='Dioptres, e.g. +2.00 or -1.50')
    quantity = fields.Integer(help='Pairs left at the camp.')

    _unique_power = models.Constraint('UNIQUE(camp_id, kind, power)', 'This power is already in the list.')

    @api.depends('kind', 'power')
    def _compute_display_name(self):
        kinds = dict(self._fields['kind'].selection)
        for g in self:
            g.display_name = f'{kinds.get(g.kind)} {g.power:+.2f}'


class CampEyeExam(models.Model):
    _name = 'camp.eye.exam'
    _description = 'Camp Eye Check'
    _inherit = ['camp.sync.mixin']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True)
    va_right = fields.Char(string='Vision right', help='e.g. 6/6, 6/18, CF (counts fingers)')
    va_left = fields.Char(string='Vision left')
    near_vision = fields.Char(help='e.g. N6, N10')
    reading_power = fields.Float(digits=(4, 2))
    findings = fields.Char(help='Comma-separated: ' + ', '.join(k for k, _l in EYE_FINDINGS))
    needs_specialist = fields.Boolean(string='Needs eye hospital')
    glasses_id = fields.Many2one('camp.glasses', string='Glasses given', ondelete='set null')
    glasses_counted = fields.Boolean(readonly=True, help='Taken off the glasses stock.')
    notes = fields.Char()
    examined_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)

    def _take_glasses(self):
        for e in self.filtered(lambda e: e.glasses_id and not e.glasses_counted):
            glasses = e.glasses_id.sudo()
            if glasses.quantity <= 0:
                raise UserError(_('No %s glasses left at this camp.', glasses.display_name))
            glasses.quantity -= 1
            e.glasses_counted = True

    @api.model_create_multi
    def create(self, vals_list):
        exams = super().create(vals_list)
        exams._take_glasses()
        return exams

    def write(self, vals):
        res = super().write(vals)
        if 'glasses_id' in vals:
            self._take_glasses()
        return res


class CampVisitPhoto(models.Model):
    """A clinical photo (wound, skin, eye), only with the patient's consent."""
    _name = 'camp.visit.photo'
    _description = 'Camp Clinical Photo'
    _inherit = ['camp.sync.mixin']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    image = fields.Image(max_width=1600, max_height=1600, attachment=True)
    note = fields.Char(help='e.g. Left leg ulcer')
    consent = fields.Boolean(required=True, help='The patient agreed to this photo for their care.')
    taken_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)

    @api.constrains('consent')
    def _check_consent(self):
        if any(not p.consent for p in self):
            raise UserError(_('A clinical photo needs the patient\'s consent.'))


class CampAncCheck(models.Model):
    """Pregnancy check: weeks, danger signs. Danger signs make the visit urgent."""
    _name = 'camp.anc.check'
    _description = 'Camp Pregnancy Check'
    _inherit = ['camp.sync.mixin']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    weeks = fields.Integer(string='Weeks pregnant')
    danger_signs = fields.Char(help='Comma-separated: ' + ', '.join(k for k, _l in ANC_DANGER_SIGNS))
    tt_given = fields.Boolean(string='Tetanus vaccine given today')
    notes = fields.Char()
    high_risk = fields.Boolean(compute='_compute_high_risk', store=True)

    @api.depends('danger_signs')
    def _compute_high_risk(self):
        for a in self:
            a.high_risk = bool((a.danger_signs or '').strip())

    def _mark_visit(self):
        for a in self:
            a.visit_id.sudo().write({'pregnant': True, **({'priority': 'urgent'} if a.high_risk else {})})

    @api.model_create_multi
    def create(self, vals_list):
        checks = super().create(vals_list)
        checks._mark_visit()
        return checks

    def write(self, vals):
        res = super().write(vals)
        if 'danger_signs' in vals:
            self._mark_visit()
        return res


class CampVaccineRecord(models.Model):
    """A child's vaccine: had before (from the card), given today, or missed."""
    _name = 'camp.vaccine.record'
    _description = 'Camp Child Vaccine'
    _inherit = ['camp.sync.mixin']
    _order = 'id'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True)
    vaccine = fields.Selection([(k, label) for k, label, _w in VACCINES], required=True)
    status = fields.Selection([('had', 'Had before (card)'), ('given', 'Given today'), ('missed', 'Missed — refer')],
                              required=True)
    age_months = fields.Integer()

    _one_per_visit = models.Constraint('UNIQUE(visit_id, vaccine)', 'This vaccine is already recorded for the visit.')


class CampVisit(models.Model):
    _inherit = 'camp.visit'

    eye_exam_ids = fields.One2many('camp.eye.exam', 'visit_id', string='Eye checks')
    photo_ids = fields.One2many('camp.visit.photo', 'visit_id', string='Photos')
    anc_check_ids = fields.One2many('camp.anc.check', 'visit_id', string='Pregnancy checks')
    vaccine_record_ids = fields.One2many('camp.vaccine.record', 'visit_id', string='Vaccines')
