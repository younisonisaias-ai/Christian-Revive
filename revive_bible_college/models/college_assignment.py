from odoo import api, fields, models

from .college_app_api import public_student


class CollegeAssignment(models.Model):
    _name = 'college.assignment'
    _description = 'Bible College Assignment'
    _order = 'due_date, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True)
    term_id = fields.Many2one('college.term', required=True)
    description = fields.Text()
    due_date = fields.Date()
    max_score = fields.Float(default=100.0)
    active = fields.Boolean(default=True)
    submission_ids = fields.One2many('college.submission', 'assignment_id', string='Submissions')
    submission_count = fields.Integer(compute='_compute_submission_count')

    def _compute_submission_count(self):
        for assignment in self:
            assignment.submission_count = len(assignment.submission_ids)

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Submissions',
            'res_model': 'college.submission',
            'view_mode': 'list,form',
            'domain': [('assignment_id', '=', self.id)],
            'context': {'default_assignment_id': self.id},
        }

    # ── App API (Phase 9: public student side, no login) ─────────
    # A student only sees/submits assignments for a (course, term) pair
    # they are actually enrolled in — re-checked here, not assumed from
    # the app's own UI, same as app_college_student_content.

    @api.model
    def app_college_student_assignments(self, code, email):
        student = public_student(self.env, code, email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        pairs = {(e.course_id.id, e.term_id.id) for e in student.enrollment_ids}
        assignments = self.sudo().search([('active', '=', True)])
        assignments = assignments.filtered(lambda a: (a.course_id.id, a.term_id.id) in pairs)
        Submission = self.env['college.submission'].sudo()
        result = []
        for assignment in assignments:
            submission = Submission.search([
                ('assignment_id', '=', assignment.id), ('student_id', '=', student.id),
            ], limit=1)
            result.append({
                'id': assignment.id, 'name': assignment.name,
                'course_name': assignment.course_id.name, 'term_name': assignment.term_id.name,
                'due_date': assignment.due_date.isoformat() if assignment.due_date else '',
                'max_score': assignment.max_score, 'description': assignment.description or '',
                'submission_state': submission.state if submission else 'none',
                'score': submission.score if submission and submission.state == 'graded' else None,
                'feedback': submission.feedback if submission and submission.state == 'graded' else '',
            })
        return {'success': True, 'assignments': result}

    @api.model
    def app_college_student_submit_assignment(self, code, email, assignment_id,
                                                text_answer='', attachment=None, attachment_filename=''):
        student = public_student(self.env, code, email)
        if not student:
            return {'success': False, 'error': 'No student found with that number and email'}
        assignment = self.sudo().browse(assignment_id)
        if not assignment.exists():
            return {'success': False, 'error': 'Assignment not found'}
        pairs = {(e.course_id.id, e.term_id.id) for e in student.enrollment_ids}
        if (assignment.course_id.id, assignment.term_id.id) not in pairs:
            return {'success': False, 'error': 'You are not enrolled in this course'}
        text_answer = (text_answer or '').strip()[:10000]
        if not text_answer and not attachment:
            return {'success': False, 'error': 'Write an answer or attach a file'}
        Submission = self.env['college.submission'].sudo()
        submission = Submission.search([
            ('assignment_id', '=', assignment_id), ('student_id', '=', student.id),
        ], limit=1)
        if submission and submission.state != 'draft':
            return {'success': False, 'error': 'You already submitted this assignment'}
        vals = {'text_answer': text_answer}
        if attachment:
            vals['attachment'] = attachment
            vals['attachment_filename'] = (attachment_filename or '')[:200]
        if submission:
            submission.write(vals)
        else:
            vals.update({'assignment_id': assignment_id, 'student_id': student.id})
            submission = Submission.create(vals)
        submission.action_submit()
        return {'success': True, 'state': submission.state}
