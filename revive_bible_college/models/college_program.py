from odoo import api, fields, models

from .college_app_api import college_app_staff


class CollegeProgram(models.Model):
    _name = 'college.program'
    _description = 'Bible College Program'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char()
    level = fields.Selection([
        ('certificate', 'Certificate'),
        ('diploma', 'Diploma'),
        ('bachelor', "Bachelor's"),
        ('master', "Master's"),
        ('other', 'Other'),
    ], default='certificate', required=True)
    duration_terms = fields.Integer(string='Duration (terms)', default=1)
    description = fields.Text()
    active = fields.Boolean(default=True)

    # ── App API (Phase 8: staff side) ────────────────────────────
    # Dropdown data for the app's applicant/student/enrollment screens.

    @api.model
    def app_college_get_lookups(self):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        programs = self.sudo().search([], order='name')
        terms = self.env['college.term'].sudo().search([], order='start_date desc')
        courses = self.env['college.course'].sudo().search([], order='name')
        return {
            'success': True,
            'programs': [{'id': p.id, 'name': p.name} for p in programs],
            'terms': [{'id': t.id, 'name': t.name} for t in terms],
            'courses': [{'id': c.id, 'name': c.name, 'program_id': c.program_id.id} for c in courses],
        }

    # ── App API (Phase 9: public applicant side, no login) ───────

    @api.model
    def app_college_public_lookups(self):
        programs = self.sudo().search([('active', '=', True)], order='name')
        terms = self.env['college.term'].sudo().search([('state', '!=', 'closed')], order='start_date desc')
        return {
            'success': True,
            'programs': [{'id': p.id, 'name': p.name} for p in programs],
            'terms': [{'id': t.id, 'name': t.name} for t in terms],
        }
