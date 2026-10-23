from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMusicArtist(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Param = self.env['ir.config_parameter'].sudo()
        self.Param.set_param('revive.music_artist_name', 'God of Life')
        self.Track = self.env['music.track']

    def test_client_church_publishes_under_its_ministry_name(self):
        self.Param.set_param('revive.music_any_artist', 'False')
        track = self.Track.create({'name': 'A song', 'artist': 'Someone Famous'})
        self.assertEqual(track.artist, 'God of Life')
        self.assertTrue(track.artist_locked)
        track.write({'artist': 'Another Artist'})
        self.assertEqual(track.artist, 'God of Life')
        # Other edits leave the artist alone.
        track.write({'name': 'Renamed'})
        self.assertEqual(track.artist, 'God of Life')

    def test_christian_revive_may_use_any_artist(self):
        self.Param.set_param('revive.music_any_artist', 'True')
        track = self.Track.create({'name': 'A song', 'artist': 'Anil Samuel'})
        self.assertEqual(track.artist, 'Anil Samuel')
        self.assertFalse(track.artist_locked)
