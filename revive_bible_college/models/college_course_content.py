from odoo import fields, models


class CollegeCourseContent(models.Model):
    _name = 'college.course.content'
    _description = 'Bible College Course Material'
    _order = 'course_id, sequence, id'

    name = fields.Char(required=True)
    course_id = fields.Many2one('college.course', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    content_type = fields.Selection([
        ('document', 'Document'),
        ('video', 'Video Link'),
        ('link', 'Link'),
        ('text', 'Text'),
    ], default='document', required=True)
    attachment = fields.Binary(attachment=True)
    attachment_filename = fields.Char()
    url = fields.Char(string='Link / Video URL')
    body = fields.Text(string='Text Content')
    active = fields.Boolean(default=True)
