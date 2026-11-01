from odoo import fields, models


class CollegeSermon(models.Model):
    _name = 'college.sermon'
    _description = 'Bible College Sermon Submission'
    _order = 'sermon_date desc, id desc'
    _rec_name = 'title'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade')
    course_id = fields.Many2one('college.course')
    title = fields.Char(required=True)
    scripture_passage = fields.Char(string='Scripture Passage')
    sermon_date = fields.Date(default=fields.Date.context_today)
    manuscript = fields.Text(string='Manuscript / Outline')
    audio = fields.Binary(attachment=True)
    audio_filename = fields.Char()
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed', 'Reviewed'),
    ], default='draft', required=True)
    reviewer_id = fields.Many2one('res.users', readonly=True, copy=False)
    review_date = fields.Date(readonly=True, copy=False)
    score = fields.Float()
    feedback = fields.Text()

    def action_submit(self):
        for sermon in self:
            if sermon.state != 'draft':
                continue
            sermon.state = 'submitted'

    def action_complete_review(self):
        for sermon in self:
            if sermon.state != 'submitted':
                continue
            sermon.write({
                'state': 'reviewed',
                'reviewer_id': self.env.user.id,
                'review_date': fields.Date.context_today(self),
            })

    def action_reset_to_draft(self):
        self.write({
            'state': 'draft',
            'reviewer_id': False,
            'review_date': False,
        })
