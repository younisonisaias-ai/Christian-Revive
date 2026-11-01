from odoo import api, fields, models

from .college_app_api import college_app_staff, normalize_code

APPLICANT_ACTIONS = {
    'submit': 'action_submit',
    'under_review': 'action_under_review',
    'accept': 'action_accept',
    'reject': 'action_reject',
    'enroll': 'action_enroll',
}


class CollegeApplicant(models.Model):
    _name = 'college.applicant'
    _description = 'Bible College Applicant'
    _inherit = ['mail.thread']
    _order = 'id desc'

    applicant_code = fields.Char(readonly=True, copy=False,
                                  default=lambda self: self.env['ir.sequence'].next_by_code('college.applicant'))
    name = fields.Char(required=True, tracking=True)
    email = fields.Char()
    phone = fields.Char()
    program_id = fields.Many2one('college.program', required=True, tracking=True)
    term_id = fields.Many2one('college.term', string='Applying For Term')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('under_review', 'Under Review'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('enrolled', 'Enrolled'),
    ], default='draft', required=True, tracking=True)
    submitted_date = fields.Date(readonly=True)
    decision_date = fields.Date(readonly=True)
    decision_notes = fields.Text()
    student_id = fields.Many2one('college.student', readonly=True, copy=False)

    def action_submit(self):
        self.write({'state': 'submitted', 'submitted_date': fields.Date.context_today(self)})

    def action_under_review(self):
        self.write({'state': 'under_review'})

    def action_accept(self):
        self.write({'state': 'accepted', 'decision_date': fields.Date.context_today(self)})

    def action_reject(self):
        self.write({'state': 'rejected', 'decision_date': fields.Date.context_today(self)})

    def action_enroll(self):
        Student = self.env['college.student']
        for applicant in self:
            if applicant.state != 'accepted':
                continue
            student = Student.create({
                'name': applicant.name,
                'email': applicant.email,
                'phone': applicant.phone,
                'program_id': applicant.program_id.id,
                'enrolled_term_id': applicant.term_id.id,
                'applicant_id': applicant.id,
            })
            applicant.write({'state': 'enrolled', 'student_id': student.id})

    # ── App API (Phase 8: staff side) ────────────────────────────

    def _app_data(self):
        return {
            'id': self.id, 'code': self.applicant_code or '', 'name': self.name,
            'email': self.email or '', 'phone': self.phone or '',
            'program_id': self.program_id.id, 'program_name': self.program_id.name,
            'term_id': self.term_id.id, 'term_name': self.term_id.name or '',
            'state': self.state,
            'submitted_date': self.submitted_date.isoformat() if self.submitted_date else '',
            'decision_date': self.decision_date.isoformat() if self.decision_date else '',
            'decision_notes': self.decision_notes or '',
            'student_id': self.student_id.id or False,
            'student_code': self.student_id.student_code or '',
        }

    @api.model
    def app_college_get_applicants(self, state=None, query=''):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        domain = []
        if state:
            domain.append(('state', '=', state))
        if query:
            domain.append(('name', 'ilike', query))
        applicants = self.sudo().search(domain, order='id desc', limit=200)
        return {'success': True, 'applicants': [a._app_data() for a in applicants]}

    @api.model
    def app_college_create_applicant(self, vals=None):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        allowed = {'name', 'email', 'phone', 'program_id', 'term_id'}
        clean_vals = {k: v for k, v in (vals or {}).items() if k in allowed}
        if not clean_vals.get('name') or not clean_vals.get('program_id'):
            return {'success': False, 'error': 'Name and program are required'}
        applicant = self.sudo().create(clean_vals)
        return {'success': True, 'applicant': applicant._app_data()}

    @api.model
    def app_college_update_applicant(self, applicant_id, vals=None):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        applicant = self.sudo().browse(applicant_id)
        if not applicant.exists():
            return {'success': False, 'error': 'Applicant not found'}
        allowed = {'name', 'email', 'phone', 'program_id', 'term_id', 'decision_notes'}
        clean_vals = {k: v for k, v in (vals or {}).items() if k in allowed}
        applicant.write(clean_vals)
        return {'success': True, 'applicant': applicant._app_data()}

    @api.model
    def app_college_applicant_action(self, applicant_id, action):
        staff, _is_admin = college_app_staff(self.env)
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        applicant = self.sudo().browse(applicant_id)
        if not applicant.exists():
            return {'success': False, 'error': 'Applicant not found'}
        method = APPLICANT_ACTIONS.get(action)
        if not method:
            return {'success': False, 'error': 'Unknown action'}
        getattr(applicant, method)()
        return {'success': True, 'applicant': applicant._app_data()}

    # ── App API (Phase 9: public applicant side, no login) ───────
    # Anyone can apply; checking status afterwards needs both the
    # applicant code AND the matching email, since there is no account.

    @api.model
    def app_college_public_apply(self, vals=None):
        vals = vals or {}
        name = ' '.join(str(vals.get('name') or '').split())[:200]
        email = str(vals.get('email') or '').strip()[:200]
        phone = str(vals.get('phone') or '').strip()[:50]
        program_id = vals.get('program_id')
        term_id = vals.get('term_id') or False
        if not name or not email or '@' not in email:
            return {'success': False, 'error': 'A name and a valid email are required'}
        program = self.env['college.program'].sudo().browse(program_id) if program_id else None
        if not program or not program.exists():
            return {'success': False, 'error': 'Choose a program'}
        if term_id and not self.env['college.term'].sudo().browse(term_id).exists():
            term_id = False
        applicant = self.sudo().create({
            'name': name, 'email': email, 'phone': phone,
            'program_id': program.id, 'term_id': term_id,
            'state': 'submitted', 'submitted_date': fields.Date.context_today(self),
        })
        return {'success': True, 'applicant': applicant._app_data()}

    @api.model
    def app_college_check_application(self, code, email):
        code = normalize_code(code, 'APP-')
        email = str(email or '').strip().lower()
        if not code or not email:
            return {'success': False, 'error': 'Enter your application number and email'}
        applicant = self.sudo().search([
            ('applicant_code', '=ilike', code), ('email', '!=', False),
        ], limit=1).filtered(lambda a: a.email.strip().lower() == email)
        if not applicant:
            return {'success': False, 'error': 'No application found with that number and email'}
        return {'success': True, 'applicant': applicant._app_data()}
