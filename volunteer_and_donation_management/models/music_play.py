"""How often each song is played in the app, per day.

The app reports a play once a song has played for 30 seconds. No listener
is recorded: only "song X was played N times on this day".
"""
from datetime import timedelta

from odoo import api, fields, models

# One phone can't report more than this many plays of one song at once.
MAX_PLAYS_PER_REPORT = 50


class MusicTrackPlay(models.Model):
    _name = 'music.track.play'
    _description = 'Song plays per day'
    _order = 'date desc, plays desc'
    _rec_name = 'track_id'

    track_id = fields.Many2one('music.track', string='Song', required=True, ondelete='cascade', index=True)
    artist = fields.Char(related='track_id.artist', store=True, string='Artist')
    language = fields.Selection(related='track_id.language', store=True)
    date = fields.Date(required=True, index=True, default=fields.Date.context_today)
    plays = fields.Integer(default=0, aggregator='sum')

    _track_date_uniq = models.Constraint('unique(track_id, date)', 'One row per song per day.')


class MusicTrack(models.Model):
    _inherit = 'music.track'

    play_count = fields.Integer(string='Plays', readonly=True, default=0, copy=False,
                                help='Times played in the app (30 seconds or more).')

    @api.model
    def app_record_plays(self, plays):
        """Adds plays reported by the app: {"<track id>": count}."""
        counts = {}
        for key, value in (plays or {}).items():
            try:
                track_id, n = int(key), int(value)
            except (TypeError, ValueError):
                continue
            if n > 0:
                counts[track_id] = counts.get(track_id, 0) + min(n, MAX_PLAYS_PER_REPORT)
        if not counts:
            return {'success': True, 'recorded': 0}
        tracks = self.sudo().browse(list(counts)).exists()
        today = fields.Date.context_today(self)
        for track in tracks:
            n = counts[track.id]
            # Upserts so phones reporting at the same time never lose a play.
            self.env.cr.execute(
                """INSERT INTO music_track_play (track_id, artist, language, date, plays,
                                                 create_uid, create_date, write_uid, write_date)
                   VALUES (%s, %s, %s, %s, %s, %s, now() at time zone 'utc', %s, now() at time zone 'utc')
                   ON CONFLICT (track_id, date) DO UPDATE SET plays = music_track_play.plays + EXCLUDED.plays""",
                (track.id, track.artist or None, track.language or None, today, n, self.env.uid, self.env.uid),
            )
            self.env.cr.execute(
                'UPDATE music_track SET play_count = COALESCE(play_count, 0) + %s WHERE id = %s', (n, track.id))
        self.env['music.track.play'].invalidate_model()
        tracks.invalidate_recordset(['play_count'])
        return {'success': True, 'recorded': sum(counts[t.id] for t in tracks)}

    @api.model
    def app_top_tracks(self, days=30, limit=10):
        """Most played published songs of the last [days] days, most first."""
        days = max(1, min(int(days or 30), 366))
        limit = max(1, min(int(limit or 10), 50))
        since = fields.Date.context_today(self) - timedelta(days=days - 1)
        groups = self.env['music.track.play'].sudo()._read_group(
            [('date', '>=', since), ('track_id.is_published', '=', True)],
            ['track_id'], ['plays:sum'], order='plays:sum desc', limit=limit)
        return {'success': True, 'days': days,
                'tracks': [{'track_id': track.id, 'plays': total} for track, total in groups if total]}
