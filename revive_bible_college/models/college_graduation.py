from odoo import _, fields, models
from odoo.exceptions import UserError


class CollegeGraduationRequirement(models.Model):
    _name = 'college.graduation.requirement'
    _description = 'Graduation Requirement'
    _order = 'sequence, id'

    name = fields.Char(required=True, help='e.g. "Minimum Credits Completed", "All Fees Paid"')
    program_id = fields.Many2one('college.program', help='Leave blank to apply to every program.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


class CollegeGraduationClearance(models.Model):
    _name = 'college.graduation.clearance'
    _description = 'Bible College Graduation Clearance'
    _order = 'id desc'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    term_id = fields.Many2one('college.term', string='Expected Graduation Term')
    state = fields.Selection([
        ('draft', 'In Progress'),
        ('cleared', 'Cleared'),
        ('graduated', 'Graduated'),
    ], default='draft', required=True)
    cleared_by = fields.Many2one('res.users', readonly=True, copy=False)
    cleared_date = fields.Date(readonly=True, copy=False)
    checklist_ids = fields.One2many('college.graduation.checklist.line', 'clearance_id', string='Checklist')
    notes = fields.Text()

    def action_load_requirements(self):
        Requirement = self.env['college.graduation.requirement']
        for clearance in self:
            existing = clearance.checklist_ids.requirement_id.ids
            requirements = Requirement.search([
                '|', ('program_id', '=', False), ('program_id', '=', clearance.student_id.program_id.id),
            ])
            new_lines = [{
                'clearance_id': clearance.id, 'requirement_id': requirement.id,
            } for requirement in requirements if requirement.id not in existing]
            if new_lines:
                self.env['college.graduation.checklist.line'].create(new_lines)

    def action_mark_cleared(self):
        for clearance in self:
            if clearance.state != 'draft':
                continue
            if not clearance.checklist_ids:
                raise UserError(_('Load the graduation requirements first.'))
            if any(not line.done for line in clearance.checklist_ids):
                raise UserError(_('Every requirement must be checked off before clearing this student.'))
            clearance.write({
                'state': 'cleared',
                'cleared_by': self.env.user.id,
                'cleared_date': fields.Date.context_today(self),
            })

    def action_graduate(self):
        for clearance in self:
            if clearance.state != 'cleared':
                continue
            clearance.state = 'graduated'
            clearance.student_id.state = 'graduated'

    def action_reset_to_draft(self):
        for clearance in self:
            if clearance.state == 'graduated':
                clearance.student_id.state = 'active'
            clearance.write({'state': 'draft', 'cleared_by': False, 'cleared_date': False})


class CollegeGraduationChecklistLine(models.Model):
    _name = 'college.graduation.checklist.line'
    _description = 'Graduation Checklist Line'
    _order = 'id'

    clearance_id = fields.Many2one('college.graduation.clearance', required=True, ondelete='cascade')
    requirement_id = fields.Many2one('college.graduation.requirement', required=True)
    done = fields.Boolean()
    notes = fields.Char()

    _clearance_requirement_uniq = models.Constraint(
        'unique(clearance_id, requirement_id)',
        'This requirement is already on this student\'s checklist.',
    )
