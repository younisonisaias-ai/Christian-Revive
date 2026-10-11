"""Settings the medical lead controls: specialities, red-flag thresholds,
dose templates, diagnosis codes and the camp formulary (approved medicines)."""
import operator as py_operator

from odoo import api, fields, models
from odoo.exceptions import ValidationError

VITAL_MEASURES = [
    ('bp_systolic', 'BP systolic (mmHg)'),
    ('bp_diastolic', 'BP diastolic (mmHg)'),
    ('pulse', 'Pulse (/min)'),
    ('temperature', 'Temperature (°C)'),
    ('spo2', 'SpO2 (%)'),
    ('bmi', 'BMI'),
    ('blood_sugar', 'Blood sugar (mg/dL)'),
    ('hemoglobin', 'Haemoglobin (g/dL)'),
]
OPERATORS = {'>': py_operator.gt, '>=': py_operator.ge, '<': py_operator.lt, '<=': py_operator.le}
PRIORITIES = [('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')]


class CampSpeciality(models.Model):
    _name = 'camp.speciality'
    _description = 'Camp Speciality'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    name_ur = fields.Char(string='Name (Urdu)')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class CampFlagRule(models.Model):
    _name = 'camp.flag.rule'
    _description = 'Red-flag Threshold'
    _order = 'measure, sequence'

    name = fields.Char(string='Message', required=True,
                       help='Shown to the nurse and doctor, e.g. "Very high blood pressure"')
    name_ur = fields.Char(string='Message (Urdu)')
    sequence = fields.Integer(default=10)
    measure = fields.Selection(VITAL_MEASURES, required=True)
    operator = fields.Selection([(k, k) for k in OPERATORS], required=True, default='>=')
    value = fields.Float(required=True)
    priority = fields.Selection([p for p in PRIORITIES if p[0] != 'normal'],
                                required=True, default='high')
    active = fields.Boolean(default=True)

    def matches(self, vitals):
        """True when this rule is triggered by the camp.vitals record."""
        self.ensure_one()
        reading = vitals[self.measure]
        if not reading:      # not measured
            return False
        return OPERATORS[self.operator](reading, self.value)


class CampDoseTemplate(models.Model):
    _name = 'camp.dose.template'
    _description = 'Dose Template'
    _order = 'sequence, name'

    name = fields.Char(required=True, help='e.g. 1+0+1 (morning + noon + night)')
    name_ur = fields.Char(string='Instructions (Urdu)', help='e.g. صبح ایک، رات ایک')
    sequence = fields.Integer(default=10)
    doses_per_day = fields.Float(required=True, default=1,
                                 help='Units taken per day; used to work out the quantity.')
    as_needed = fields.Boolean(string='Only when needed (SOS)')
    active = fields.Boolean(default=True)


class CampDiagnosisCode(models.Model):
    _name = 'camp.diagnosis.code'
    _description = 'Diagnosis Code (ICD-10)'
    _order = 'favourite desc, code'
    _rec_names_search = ['code', 'name', 'name_ur']

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    name_ur = fields.Char(string='Name (Urdu)')
    chapter = fields.Char()
    favourite = fields.Boolean(help='Shown first in the doctor\'s search.')
    source = fields.Selection([
        ('camp', 'Camp list'),
        ('icd10', 'ICD-10-CM'),
        ('custom', 'Added by a doctor'),
    ], default='custom', required=True, index=True,
        help='Camp list: the common camp diagnoses (with Urdu names). ICD-10-CM: the full list '
             '(US NCHS, public domain). Added by a doctor: typed in Odoo or in Camp Mode.')
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', 'Each ICD-10 code can be added only once.')

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} {rec.name}' if rec.code else rec.name


class CampFormulary(models.Model):
    _name = 'camp.formulary'
    _description = 'Camp Formulary (approved medicine)'
    _order = 'sequence, product_id'

    product_id = fields.Many2one('product.product', string='Medicine', required=True,
                                 domain=[('type', '=', 'consu')], ondelete='restrict')
    strength = fields.Char(help='e.g. 500 mg, 125 mg/5 ml')
    form = fields.Selection([
        ('tablet', 'Tablet'), ('capsule', 'Capsule'), ('syrup', 'Syrup'),
        ('drops', 'Drops'), ('cream', 'Cream / ointment'), ('injection', 'Injection'),
        ('sachet', 'Sachet'), ('other', 'Other'),
    ], default='tablet')
    sequence = fields.Integer(default=10)
    default_dose_template_id = fields.Many2one('camp.dose.template', string='Default dose')
    default_days = fields.Integer(default=5)
    instructions_ur = fields.Char(string='Default instructions (Urdu)',
                                  help='e.g. کھانے کے بعد')
    active = fields.Boolean(default=True)
    # Safety checks in Camp Mode (set by the medical lead from your own guidelines).
    allergy_group = fields.Char(
        help='Words that match a patient\'s allergy, e.g. "penicillin" for amoxicillin. '
             'Separate several with commas. The medicine name is always checked too.')
    pregnancy_risk = fields.Selection([
        ('safe', 'Safe in pregnancy'),
        ('caution', 'Use with care in pregnancy'),
        ('avoid', 'Avoid in pregnancy'),
    ], help='Camp Mode warns the doctor and pharmacist when the patient is pregnant.')
    mg_per_unit = fields.Float(
        string='mg per tablet / per ml',
        help='For the child dose helper: mg in one tablet (or capsule), or in 1 ml for syrups and drops.')
    child_mg_per_kg = fields.Float(
        string='Child dose (mg/kg per dose)',
        help='Camp Mode suggests weight × this for children under 12. Leave 0 for no suggestion.')
    child_max_mg_per_kg_day = fields.Float(
        string='Child max (mg/kg per day)',
        help='Camp Mode warns when a child\'s daily amount is above weight × this.')

    _product_unique = models.Constraint('UNIQUE(product_id)', 'This medicine is already in the formulary.')

    @api.depends('product_id', 'strength')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = ' '.join(filter(None, [rec.product_id.name, rec.strength]))


class CampRxTemplate(models.Model):
    """A ready-made prescription for a common case ("Fever (adult)"): one tap
    in Camp Mode adds its diagnoses, medicines and advice. Templates without a
    doctor are shared; the ones a doctor saves in Camp Mode are theirs."""
    _name = 'camp.rx.template'
    _inherit = ['camp.sync.mixin']
    _description = 'Prescription template'
    _order = 'sequence, name'

    name = fields.Char(required=True, help='e.g. Fever (adult), Worms (child)')
    name_ur = fields.Char(string='Name (Urdu)')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        'res.users', string='Doctor', index=True, ondelete='cascade',
        default=lambda self: False if self.env.user.has_group('revive_medical_camp.group_camp_lead')
        else self.env.user,
        help='Empty: every doctor can use it. Templates a doctor saves in Camp Mode belong to that doctor.')
    diagnosis_ids = fields.Many2many('camp.diagnosis.code', string='Diagnoses')
    line_ids = fields.One2many('camp.rx.template.line', 'template_id', string='Medicines', copy=True)
    advice = fields.Text()
    advice_ur = fields.Text(string='Advice (Urdu)')
    # Moves when a medicine line changes, so phones fetch the new version.
    lines_changed_at = fields.Datetime(readonly=True)

    def _touch_lines(self):
        if self:
            self.sudo().write({'lines_changed_at': fields.Datetime.now()})


class CampRxTemplateLine(models.Model):
    _name = 'camp.rx.template.line'
    _description = 'Prescription template medicine'
    _order = 'sequence, id'

    template_id = fields.Many2one('camp.rx.template', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    formulary_id = fields.Many2one('camp.formulary', string='Camp medicine')
    outside_medicine = fields.Char(string='Or: buy outside', help='A medicine the camp does not stock.')
    dose_template_id = fields.Many2one('camp.dose.template', string='Dose')
    days = fields.Integer(default=5)
    quantity = fields.Float(help='Leave 0 to work it out from the dose and the days.')
    instructions_ur = fields.Char(string='Instructions (Urdu)')

    @api.constrains('formulary_id', 'outside_medicine')
    def _check_medicine(self):
        for line in self:
            if not line.formulary_id and not (line.outside_medicine or '').strip():
                raise ValidationError(self.env._('Choose a camp medicine or write a medicine to buy outside.'))

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.template_id._touch_lines()
        return lines

    def write(self, vals):
        res = super().write(vals)
        self.template_id._touch_lines()
        return res

    def unlink(self):
        templates = self.template_id
        res = super().unlink()
        templates.exists()._touch_lines()
        return res
