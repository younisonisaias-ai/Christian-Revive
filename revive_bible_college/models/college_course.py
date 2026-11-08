from odoo import fields, models


class CollegeCourse(models.Model):
    _name = 'college.course'
    _description = 'Bible College Course'
    _order = 'name'

    name = fields.Char(required=True)
    code = fields.Char()
    credits = fields.Float(default=1.0)
    program_id = fields.Many2one('college.program', string='Program')
    active = fields.Boolean(default=True)
    content_ids = fields.One2many('college.course.content', 'course_id', string='Course Materials')
    content_count = fields.Integer(compute='_compute_content_count')
    module_ids = fields.One2many('college.course.module', 'course_id', string='Modules')
    module_count = fields.Integer(compute='_compute_module_count')

    def _compute_content_count(self):
        for course in self:
            course.content_count = len(course.content_ids)

    def _compute_module_count(self):
        for course in self:
            course.module_count = len(course.module_ids)

    def action_view_modules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modules',
            'res_model': 'college.course.module',
            'view_mode': 'list,form',
            'domain': [('course_id', '=', self.id)],
            'context': {'default_course_id': self.id},
        }
