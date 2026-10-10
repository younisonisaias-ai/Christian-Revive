"""Settings the medical lead controls: specialities, red-flag thresholds,
dose templates, diagnosis codes and the camp formulary (approved medicines)."""
import operator as py_operator

from odoo import api, fields, models

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

    _product_unique = models.Constraint('UNIQUE(product_id)', 'This medicine is already in the formulary.')

    @api.depends('product_id', 'strength')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = ' '.join(filter(None, [rec.product_id.name, rec.strength]))
