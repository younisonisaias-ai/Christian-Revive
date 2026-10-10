"""A camp patient. Reused across camps (returning patients) and deliberately
NOT linked to contacts, members or any other app's records."""
from datetime import date

from odoo import api, fields, models


class CampPatient(models.Model):
    _name = 'camp.patient'
    _description = 'Camp Patient'
    _inherit = ['camp.sync.mixin', 'mail.thread']
    _order = 'id desc'
    _rec_names_search = ['name', 'patient_code', 'phone']

    patient_code = fields.Char(string='Patient no.', readonly=True, copy=False, index=True,
                               default=lambda self: self.env['ir.sequence'].next_by_code('camp.patient'))
    name = fields.Char(required=True, tracking=True)
    date_of_birth = fields.Date()
    age_years = fields.Integer(string='Age', compute='_compute_age', store=True, readonly=False,
                               help='Filled from the date of birth, or typed when the date is not known.')
    sex = fields.Selection([('male', 'Male'), ('female', 'Female'), ('other', 'Other')], required=True)
    phone = fields.Char()
    area = fields.Char(index=True, help='Village / neighbourhood')
    guardian_name = fields.Char(string='Guardian', help='Parent or guardian for a child.')
    consent_care = fields.Boolean(string='Consent: care & records', tracking=True,
                                  help='Required before triage.')
    consent_media = fields.Boolean(string='Consent: photos & story', tracking=True,
                                   help='Optional. Care never depends on it.')
    consent_messages = fields.Boolean(string='Consent: reminders by SMS / WhatsApp')
    active = fields.Boolean(default=True)
    visit_ids = fields.One2many('camp.visit', 'patient_id', string='Visits')
    visit_count = fields.Integer(compute='_compute_visit_count')

    _patient_code_unique = models.Constraint('UNIQUE(patient_code)', 'Patient number must be unique.')

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = date.today()
        for p in self:
            if p.date_of_birth:
                dob = p.date_of_birth
                p.age_years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    @api.depends('visit_ids')
    def _compute_visit_count(self):
        for p in self:
            p.visit_count = len(p.visit_ids)

    @api.depends('name', 'patient_code')
    def _compute_display_name(self):
        for p in self:
            p.display_name = f'{p.name} ({p.patient_code})' if p.patient_code else p.name

    def action_open_visits(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'camp.visit',
            'view_mode': 'list,form',
            'domain': [('patient_id', '=', self.id)],
            'context': {'default_patient_id': self.id},
        }
