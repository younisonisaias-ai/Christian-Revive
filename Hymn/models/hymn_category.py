from odoo import models, fields, api


class HymnCategory(models.Model):
    _name = 'hymn.category'
    _description = 'Hymn Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category (English)', required=True)
    name_urdu = fields.Char(string='Category (Urdu)',
                            help='Urdu label shown in the app, e.g. عبادت')
    code = fields.Char(string='Code', required=True,
                       help='Internal code: worship, praise, salvation, etc.')
    icon = fields.Char(string='Icon Name',
                       help='Material icon name for the app, e.g. music_note')
    sequence = fields.Integer(string='Order', default=10)
    is_active = fields.Boolean(string='Active', default=True)
    song_count = fields.Integer(string='Songs', compute='_compute_song_count')

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', 'Category code must be unique!'),
    ]

    @api.depends()
    def _compute_song_count(self):
        data = self.env['hymn.song'].read_group(
            [('category_id', 'in', self.ids)],
            ['category_id'],
            ['category_id'],
        )
        counts = {row['category_id'][0]: row['category_id_count'] for row in data if row['category_id']}
        for rec in self:
            rec.song_count = counts.get(rec.id, 0)