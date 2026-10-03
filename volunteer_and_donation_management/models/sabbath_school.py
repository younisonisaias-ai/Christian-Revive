from odoo import api, fields, models

class SabbathSchoolLesson(models.Model):
    _name = 'sabbath.school.lesson'
    _description = 'Sabbath School Lesson'
    _order = 'date desc'

    name = fields.Char(string='Title', required=True)
    date = fields.Date(string='Date', required=True)
    quarter = fields.Selection([
        ('q1', 'Q1 (Jan-Mar)'),
        ('q2', 'Q2 (Apr-Jun)'),
        ('q3', 'Q3 (Jul-Sep)'),
        ('q4', 'Q4 (Oct-Dec)'),
    ], string='Quarter', required=True)
    year = fields.Char(string='Year', required=True)
    language = fields.Selection([
        ('en', 'English'),
        ('ur', 'Urdu'),
    ], string='Language', default='en', required=True)
    description = fields.Text(string='Description')
    content = fields.Html(string='Content')
    image = fields.Binary(string='Cover Image', attachment=True)
    pdf_file = fields.Binary(string='PDF Book', attachment=True)
    pdf_filename = fields.Char(string='PDF Filename')
    video_url = fields.Char(string='Video URL')
    is_published = fields.Boolean(string='Published', default=False)

    # ── Source ──────────────────────────────────
    source_type = fields.Selection([
        ('video', 'Video (YouTube / Upload)'),
        ('cloud', 'Cloud Video (Drive/OneDrive)'),
        ('audio', 'Upload MP3'),
    ], string='Media Source', default='video', required=True)
    cloud_video_url = fields.Char(string='Cloud Video Link')
    audio_file = fields.Binary(string='MP3 File', attachment=True)
    audio_filename = fields.Char(string='MP3 Filename')

    # ── Theme song (shown as a "Theme Song" button under the lesson in the app) ──
    theme_song_file = fields.Binary(
        string='Theme Song (MP3 / MP4)', attachment=True,
        help='MP3, MP4 or M4A file. For MP4 videos the app plays the sound.')
    theme_song_filename = fields.Char(string='Theme Song Filename')
    theme_song_url = fields.Char(
        string='Theme Song Link',
        help='Optional YouTube link, or a direct link to an .mp3 / .mp4 file. '
             'If a file is uploaded as well, the uploaded file is used.')
    has_theme_song = fields.Boolean(
        string='Has Theme Song', compute='_compute_has_theme_song', store=True)

    @api.depends('theme_song_file', 'theme_song_url')
    def _compute_has_theme_song(self):
        for rec in self:
            # bin_size=True returns the file size instead of loading the whole file
            has_file = bool(rec.with_context(bin_size=True).theme_song_file)
            has_url = bool((rec.theme_song_url or '').strip())
            rec.has_theme_song = has_file or has_url

    def action_publish(self):
        self.write({'is_published': True})

    def action_unpublish(self):
        self.write({'is_published': False})