from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


URDU = 'ur_PK'


class CollegeCourse(models.Model):
    _name = 'college.course'
    _description = 'Bible College Course'
    _order = 'name'

    name = fields.Char(translate=True, required=True)
    code = fields.Char()
    credits = fields.Float(default=1.0)
    program_id = fields.Many2one('college.program', string='Program')
    active = fields.Boolean(default=True)
    content_ids = fields.One2many('college.course.content', 'course_id', string='Course Materials')
    content_count = fields.Integer(compute='_compute_content_count')
    module_ids = fields.One2many('college.course.module', 'course_id', string='Modules')
    module_count = fields.Integer(compute='_compute_module_count')

    # When a video lesson counts as finished. Each lesson can override these.
    video_min_watch_percent = fields.Integer(
        string='Watch at least (%)', default=90,
        help='How much of a video a student must actually play (skipped parts do not count) to finish it.')
    video_require_questions = fields.Boolean(
        string='Must answer every question in the video', default=True,
        help='Answering is enough; a wrong answer still counts.')

    @api.model
    def _ensure_urdu_language(self):
        """Course content can be written in Urdu as well as English (the
        app's اردو switch asks for it). Odoo has no Urdu of its own, so it
        is added here, right to left, and switched on."""
        Lang = self.env['res.lang'].sudo().with_context(active_test=False)
        urdu = Lang.search([('code', '=', URDU)], limit=1)
        if not urdu:
            Lang.create({
                'name': 'Urdu / اردو', 'code': URDU, 'iso_code': 'ur', 'url_code': 'ur',
                'direction': 'rtl', 'active': True, 'date_format': '%d/%m/%Y',
            })
        elif not urdu.active:
            urdu.active = True

    @api.constrains('video_min_watch_percent')
    def _check_video_min_watch_percent(self):
        for course in self:
            if not 0 <= course.video_min_watch_percent <= 100:
                raise ValidationError(_('"Watch at least" must be between 0 and 100%.'))

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
