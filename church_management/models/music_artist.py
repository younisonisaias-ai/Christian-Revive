"""Songs a church uploads carry its own ministry name as the artist.

Client churches (Basic, Premium, Enterprise) may only publish their own
music: the Artist field is locked to the ministry name in Settings → Church,
for new songs, edits and imports alike. Christian Revive's own ERP may
publish songs by any artist; that switch (revive.music_any_artist) is not on
the Settings page and is set by the 1.18 update on the Christian Revive ERP.
"""
from odoo import api, fields, models

ANY_ARTIST_PARAM = 'revive.music_any_artist'
ARTIST_NAME_PARAM = 'revive.music_artist_name'


class MusicTrackArtist(models.Model):
    _inherit = 'music.track'

    artist = fields.Char(default=lambda self: self._ministry_artist() or False)
    artist_locked = fields.Boolean(compute='_compute_artist_locked')

    @api.model
    def _any_artist_allowed(self):
        value = self.env['ir.config_parameter'].sudo().get_param(ANY_ARTIST_PARAM) or ''
        return value.lower() in ('1', 'true', 'yes')

    @api.model
    def _ministry_artist(self):
        """The ministry name songs are published under (company name when not set)."""
        name = (self.env['ir.config_parameter'].sudo().get_param(ARTIST_NAME_PARAM) or '').strip()
        return name or self.env.company.name or ''

    def _compute_artist_locked(self):
        locked = not self._any_artist_allowed()
        for track in self:
            track.artist_locked = locked

    @api.model_create_multi
    def create(self, vals_list):
        if not self._any_artist_allowed():
            artist = self._ministry_artist()
            for vals in vals_list:
                vals['artist'] = artist
        return super().create(vals_list)

    def write(self, vals):
        if 'artist' in vals and not self._any_artist_allowed():
            vals = dict(vals, artist=self._ministry_artist())
        return super().write(vals)
