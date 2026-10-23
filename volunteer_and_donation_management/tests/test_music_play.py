from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMusicPlay(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Track = self.env['music.track']
        self.a = self.Track.create({'name': 'Play Song A', 'artist': 'Test Band'})
        self.b = self.Track.create({'name': 'Play Song B', 'artist': 'Test Band'})
        self.hidden = self.Track.create({'name': 'Hidden', 'is_published': False})

    def test_plays_add_up_per_song_and_day(self):
        self.Track.app_record_plays({str(self.a.id): 2, str(self.b.id): 1})
        self.Track.app_record_plays({str(self.a.id): 3, 'junk': 4, '999999999': 1})
        self.assertEqual(self.a.play_count, 5)
        self.assertEqual(self.b.play_count, 1)
        rows = self.env['music.track.play'].search([('track_id', '=', self.a.id)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.plays, 5)

    def test_one_report_is_capped(self):
        self.Track.app_record_plays({str(self.a.id): 100000})
        self.assertEqual(self.a.play_count, 50)

    def test_top_tracks_most_played_first_and_published_only(self):
        self.Track.app_record_plays({str(self.a.id): 2, str(self.b.id): 7, str(self.hidden.id): 40})
        top = self.Track.app_top_tracks(days=7, limit=5)['tracks']
        ids = [t['track_id'] for t in top]
        self.assertNotIn(self.hidden.id, ids)
        self.assertLess(ids.index(self.b.id), ids.index(self.a.id))
        self.assertEqual(next(t['plays'] for t in top if t['track_id'] == self.b.id), 7)
