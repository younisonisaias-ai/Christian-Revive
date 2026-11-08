from odoo import fields, models


class CollegeCourseModule(models.Model):
    """A named group of lessons within a course (e.g. "The Pentateuch"),
    shown to students in order. Existing course materials move into one
    default module per course on upgrade — see migrations/19.0.1.12.0."""
    _name = 'college.course.module'
    _description = 'Bible College Course Module'
    _order = 'course_id, sequence, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    lesson_ids = fields.One2many('college.course.content', 'module_id', string='Lessons')
    lesson_count = fields.Integer(compute='_compute_lesson_count')

    def _compute_lesson_count(self):
        for module in self:
            module.lesson_count = len(module.lesson_ids)
