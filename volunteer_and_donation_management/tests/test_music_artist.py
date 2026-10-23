from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMusicArtist(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Artist = self.env['music.artist']
        self.Track = self.env['music.track']

    def test_add_from_songs_creates_each_artist_once(self):
        self.Track.create([
            {'name': 'Song A', 'artist': 'Zeta Choir'},
            {'name': 'Song B', 'artist': 'zeta  choir'},
            {'name': 'Song C', 'artist': 'Omega Band'},
        ])
        self.Artist.create({'name': 'Omega Band'})
        self.Artist.action_add_from_songs()
        names = self.Artist.search([('name', 'in', ['Zeta Choir', 'zeta choir', 'Omega Band'])]).mapped('name')
        self.assertEqual(sorted(n.lower() for n in names), ['omega band', 'zeta choir'])
        # Running it again adds nothing.
        before = self.Artist.search_count([])
        self.Artist.action_add_from_songs()
        self.assertEqual(self.Artist.search_count([]), before)

    def test_song_count_and_photo_flag(self):
        self.Track.create([{'name': 'One', 'artist': 'Delta Voices'}, {'name': 'Two', 'artist': 'DELTA VOICES'}])
        artist = self.Artist.create({'name': 'Delta Voices'})
        self.assertEqual(artist.track_count, 2)
        self.assertFalse(artist.has_image)
        # 1x1 PNG
        artist.image_1920 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
        self.assertTrue(artist.has_image)
