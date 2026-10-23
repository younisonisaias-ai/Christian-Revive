"""Artists of the music library: a photo and a short bio for each.

Songs keep their artist as plain text; an artist here is matched to songs
by name (ignoring case and spaces), so existing songs need no changes.
"""
from odoo import api, fields, models


def _artist_key(name):
    return ' '.join((name or '').split()).lower()


class MusicArtist(models.Model):
    _name = 'music.artist'
    _description = 'Music Artist'
    _inherit = ['image.mixin']
    _order = 'name'

    name = fields.Char(required=True)
    bio = fields.Text(string='About')
    active = fields.Boolean(default=True)
    has_image = fields.Boolean(compute='_compute_has_image', store=True)
    track_count = fields.Integer(string='Songs', compute='_compute_track_count')

    _name_unique = models.Constraint('UNIQUE(name)', 'This artist already exists.')

    @api.depends('image_1920')
    def _compute_has_image(self):
        for artist in self:
            artist.has_image = bool(artist.image_1920)

    def _compute_track_count(self):
        counts = {}
        for name, count in self.env['music.track']._read_group([('artist', '!=', False)], ['artist'], ['__count']):
            key = _artist_key(name)
            counts[key] = counts.get(key, 0) + count
        for artist in self:
            artist.track_count = counts.get(_artist_key(artist.name), 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name'):
                vals['name'] = ' '.join(vals['name'].split())
        return super().create(vals_list)

    @api.model
    def action_add_from_songs(self):
        """Adds an artist for every song artist that has none yet."""
        Track = self.env['music.track'].with_context(active_test=False)
        known = {_artist_key(a.name) for a in self.with_context(active_test=False).search([])}
        new = {}
        for name in Track.search([('artist', '!=', False)]).mapped('artist'):
            key = _artist_key(name)
            if key and key not in known and key not in new:
                new[key] = ' '.join(name.split())
        if new:
            self.create([{'name': n} for n in new.values()])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Artists',
                'message': f'{len(new)} artist(s) added from your songs.' if new else 'Every song artist is already listed.',
                'type': 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_view_songs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'music.track',
            'view_mode': 'list,form',
            'domain': [('artist', '=ilike', self.name)],
            'context': {'default_artist': self.name},
        }
