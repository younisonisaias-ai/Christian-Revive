import logging

from odoo import fields, models, api
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta, date
import pytz

_logger = logging.getLogger(__name__)


class LiveStream(models.Model):
    _name = 'crtv.live.stream'
    _description = 'CRTV Live Stream'
    _order = 'air_date asc, air_time asc'
    _rec_name = 'name'

    # ── Basic Info ────────────────────────────────────────────
    name        = fields.Char(string='Program Title', required=True)
    subtitle    = fields.Char(string='Episode / Subtitle')
    description = fields.Text(string='Description')
    thumbnail   = fields.Binary(string='Thumbnail Image')

    # ── Scheduling ────────────────────────────────────────────
    air_date = fields.Date(
        string='Air Date',
        required=True,
        default=lambda self: self._default_air_date_and_time(language='english')[0],
        index=True,
    )
    air_time = fields.Char(
        string='Air Time (HH:MM)',
        default=lambda self: self._default_air_date_and_time(language='english')[1],
        help='24-hour LOCAL time — e.g. 09:00, 14:30, 20:00. '
             'The system will convert to UTC automatically. '
             'Defaults to right after the most recently scheduled program in the '
             'same language ends.',
    )
    duration = fields.Integer(
        string='Duration (minutes)',
        default=60,
    )
    play_for_days = fields.Integer(
        string='Play For (days)',
        default=1,
        help='How many days this video should stay active from the Air Date.',
    )
    play_until_date = fields.Date(
        string='Play Until',
        compute='_compute_play_until_date',
        store=True,
        index=True,
    )

    # Stored UTC datetimes for efficient querying — indexed for cron + status filters
    air_datetime_start = fields.Datetime(
        string='Start (UTC)',
        compute='_compute_air_datetimes',
        store=True,
        index=True,
    )
    air_datetime_end = fields.Datetime(
        string='End (UTC)',
        compute='_compute_air_datetimes',
        store=True,
        index=True,
    )

    # Human-readable local time display
    air_datetime_local = fields.Char(
        string='Local Start Time',
        compute='_compute_local_display',
        store=False,
    )

    is_live_now = fields.Boolean(
        string='Live Now',
        compute='_compute_is_live_now',
        store=False,
    )

    # ── Stream Source ─────────────────────────────────────────
    stream_type = fields.Selection([
        ('youtube',     'YouTube'),
        ('onedrive',    'OneDrive'),
        ('googledrive', 'Google Drive'),
        ('direct_url',  'Direct URL'),
        ('uploaded',    'Uploaded Video'),
    ], string='Stream Type', default='youtube', required=True)

    stream_url = fields.Char(string='Stream URL')
    video_file = fields.Binary(string='Video File')

    # ── Category & Flags ─────────────────────────────────────
    category = fields.Selection([
        ('live',    'Live Stream'),
        ('program', 'Program'),
        ('sermon',  'Sermon'),
        ('special', 'Special Event'),
        ('sabbath', 'Sabbath School'),
        ('worship', 'Worship Service'),
        ('prayer',  'Prayer Meeting'),
    ], string='Category', default='program', required=True)

    # Auto-computed — no manual editing needed
    status = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('live',      'On Air'),
        ('ended',     'Ended'),
    ], string='Status', compute='_compute_status_auto', store=True)

    is_published = fields.Boolean(string='Published', default=True)
    is_featured  = fields.Boolean(string='Featured (Main Player)')

    send_notification = fields.Boolean(string='Send Push Notification', default=False)

    # ── Language Selection ─────────────────────
    language = fields.Selection([
        ('english', 'English'),
        ('urdu', 'Urdu'),
    ], string='Language', default='english', required=True)

    # ── Default a new record to start right after the previous one (same
    # language) ends ───────────────────────────────────────────
    def _default_air_date_and_time(self, language=None):
        domain = [('language', '=', language)] if language else []
        last = self.search(domain, order='air_date desc, air_time desc', limit=1)
        if not last or not last.air_time:
            return fields.Date.today(), '09:00'
        try:
            h, m = map(int, last.air_time.split(':'))
        except Exception:
            return fields.Date.today(), '09:00'
        total_minutes = h * 60 + m + (last.duration or 60)
        days_forward, minutes_of_day = divmod(total_minutes, 24 * 60)
        new_date = last.air_date + timedelta(days=days_forward)
        new_time = '%02d:%02d' % (minutes_of_day // 60, minutes_of_day % 60)
        return new_date, new_time

    @api.onchange('language')
    def _onchange_language_default_schedule(self):
        # Only re-target a brand-new, unsaved record — never silently move
        # an existing record's schedule just because its language was edited.
        if self._origin:
            return
        new_date, new_time = self._default_air_date_and_time(language=self.language)
        self.air_date = new_date
        self.air_time = new_time

    # ── Auto-detect video duration ────────────────────────────
    def _extract_youtube_video_id(self, url):
        """Extract the 11-char video ID from common YouTube URL formats."""
        if not url:
            return False
        import re
        match = re.search(
            r'(?:youtube\.com/watch\?v=|youtube\.com/embed/|youtu\.be/|'
            r'youtube\.com/shorts/)([A-Za-z0-9_-]{11})',
            url,
        )
        return match.group(1) if match else False

    def _parse_iso8601_duration(self, iso_str):
        """Parse an ISO 8601 duration like 'PT1H2M10S' into total seconds."""
        import re
        match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', iso_str or '')
        if not match:
            return 0
        h, m, s = (int(x) if x else 0 for x in match.groups())
        return h * 3600 + m * 60 + s

    def _fetch_youtube_duration_minutes(self, url):
        """Look up a YouTube video's duration via the YouTube Data API v3.
        Requires the 'crtv_live_stream.youtube_api_key' system parameter.
        Returns whole minutes (rounded up), or False if it can't be determined."""
        video_id = self._extract_youtube_video_id(url)
        if not video_id:
            _logger.warning('Could not extract a YouTube video ID from %s', url)
            return False
        api_key = self.env['ir.config_parameter'].sudo().get_param(
            'crtv_live_stream.youtube_api_key')
        if not api_key:
            _logger.warning(
                'No YouTube API key configured (system parameter '
                'crtv_live_stream.youtube_api_key) — cannot auto-detect duration for %s', url)
            return False
        import json, urllib.request, urllib.parse
        try:
            query = urllib.parse.urlencode(
                {'id': video_id, 'part': 'contentDetails', 'key': api_key})
            req_url = f'https://www.googleapis.com/youtube/v3/videos?{query}'
            with urllib.request.urlopen(req_url, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            items = data.get('items') or []
            if not items:
                _logger.warning(
                    'YouTube API returned no items for video %s (response=%s)',
                    video_id, data)
                return False
            iso_duration = items[0]['contentDetails']['duration']
            seconds = self._parse_iso8601_duration(iso_duration)
            if not seconds:
                return False
            return max(1, -(-seconds // 60))
        except Exception:
            _logger.exception('YouTube API call failed for video %s', video_id)
            return False

    def _fetch_file_duration_minutes(self, video_binary):
        """Inspect an uploaded video file's duration via ffprobe.
        Returns whole minutes (rounded up), or False if it can't be determined."""
        if not video_binary:
            return False
        import base64, subprocess, tempfile, os, json
        try:
            raw = base64.b64decode(video_binary)
        except Exception:
            return False
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'json', tmp_path],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(result.stdout or '{}')
            seconds = float(data.get('format', {}).get('duration') or 0)
            if not seconds:
                _logger.warning('ffprobe returned no duration (stderr=%s)', result.stderr)
                return False
            return max(1, -(-int(seconds) // 60))
        except Exception:
            _logger.exception('ffprobe failed to read uploaded video duration')
            return False
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    @api.onchange('stream_type', 'stream_url')
    def _onchange_stream_url_duration(self):
        if self.stream_type == 'youtube' and self.stream_url:
            minutes = self._fetch_youtube_duration_minutes(self.stream_url)
            if minutes:
                self.duration = minutes

    @api.onchange('stream_type', 'video_file')
    def _onchange_video_file_duration(self):
        if self.stream_type == 'uploaded' and self.video_file:
            minutes = self._fetch_file_duration_minutes(self.video_file)
            if minutes:
                self.duration = minutes

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('duration'):
                continue
            minutes = False
            if vals.get('stream_type') == 'youtube' and vals.get('stream_url'):
                minutes = self._fetch_youtube_duration_minutes(vals['stream_url'])
            elif vals.get('stream_type') == 'uploaded' and vals.get('video_file'):
                minutes = self._fetch_file_duration_minutes(vals['video_file'])
            if minutes:
                vals['duration'] = minutes
        return super().create(vals_list)

    # ── Cascade: keep the back-to-back chain in sync when a record's
    # schedule changes ─────────────────────────────────────────
    def _abs_minutes(self, rec_date, time_str):
        if not rec_date or not time_str:
            return 0
        try:
            h, m = map(int, time_str.split(':'))
        except Exception:
            h, m = 0, 0
        return rec_date.toordinal() * 24 * 60 + h * 60 + m

    def _minutes_to_date_time(self, abs_minutes):
        days, minutes_of_day = divmod(abs_minutes, 24 * 60)
        new_date = date.fromordinal(days)
        h, m = divmod(minutes_of_day, 60)
        return new_date, '%02d:%02d' % (h, m)

    def write(self, vals):
        # Only duration/air_time changes cascade to keep the lineup
        # back-to-back. Moving a record to a different air_date on its own
        # is a deliberate "relocate this one lesson" action and must stay
        # isolated to that single record.
        schedule_fields = {'duration', 'air_time'}
        if self.env.context.get('skip_schedule_cascade') or not (
            schedule_fields & set(vals.keys())
        ):
            return super().write(vals)

        before = {
            rec.id: (rec.language, self._abs_minutes(rec.air_date, rec.air_time))
            for rec in self
        }

        res = super().write(vals)

        for rec in self:
            language, old_start = before.get(rec.id, (None, None))
            if old_start is None:
                continue
            # Walk every same-language record that was scheduled after this one
            # (in its existing chronological order) and re-chain each one
            # directly off the end of the one before it — fully collapsing
            # whatever gap previously existed, so the lineup is back-to-back
            # from this point forward.
            downstream = self.search([
                ('language', '=', language),
                ('id', '!=', rec.id),
            ]).filtered(
                lambda r: self._abs_minutes(r.air_date, r.air_time) > old_start
            ).sorted(key=lambda r: self._abs_minutes(r.air_date, r.air_time))

            cursor = self._abs_minutes(rec.air_date, rec.air_time) + (rec.duration or 60)
            for d in downstream:
                new_date, new_time = self._minutes_to_date_time(cursor)
                d.with_context(skip_schedule_cascade=True).write({
                    'air_date': new_date,
                    'air_time': new_time,
                })
                cursor += (d.duration or 60)
        return res

    # ── Get server/user timezone ──────────────────────────────
    @api.depends('air_date', 'play_for_days')
    def _compute_play_until_date(self):
        for rec in self:
            if not rec.air_date:
                rec.play_until_date = False
                continue
            days = max(rec.play_for_days or 1, 1)
            rec.play_until_date = rec.air_date + timedelta(days=days - 1)

    def _get_tz(self):
        """Return the active timezone — user tz > system tz > Asia/Karachi."""
        tz_name = (
            self.env.user.tz
            or self.env['ir.config_parameter'].sudo().get_param(
                'system.timezone', 'Asia/Karachi')
        )
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.timezone('Asia/Karachi')


    # ── Convert local air_date + air_time → UTC Datetime ─────
    @api.depends('air_date', 'air_time', 'duration')
    def _compute_air_datetimes(self):
        for rec in self:
            try:
                h, m = map(int, (rec.air_time or '00:00').split(':'))
                tz = rec._get_tz()

                # Build naive local datetime
                local_naive = datetime(
                    rec.air_date.year,
                    rec.air_date.month,
                    rec.air_date.day,
                    h, m, 0,
                )

                # Localise → convert to UTC → strip tzinfo for Odoo storage
                local_aware = tz.localize(local_naive, is_dst=None)
                utc_start   = local_aware.astimezone(pytz.UTC).replace(tzinfo=None)
                utc_end     = utc_start + timedelta(minutes=rec.duration or 60)

                rec.air_datetime_start = utc_start
                rec.air_datetime_end   = utc_end

            except Exception:
                rec.air_datetime_start = False
                rec.air_datetime_end   = False

    # ── Human-readable local time display ─────────────────────
    def _compute_local_display(self):
        for rec in self:
            try:
                if not rec.air_datetime_start:
                    rec.air_datetime_local = ''
                    continue
                tz = rec._get_tz()
                local_dt = pytz.UTC.localize(
                    rec.air_datetime_start).astimezone(tz)
                rec.air_datetime_local = local_dt.strftime('%Y-%m-%d %H:%M (%Z)')
            except Exception:
                rec.air_datetime_local = ''

    # ── Auto status from current UTC time ─────────────────────
    def _active_window_utc_end(self):
        self.ensure_one()
        if not self.air_date:
            return False
        try:
            tz = self._get_tz()
            days = max(self.play_for_days or 1, 1)
            local_end_date = self.air_date + timedelta(days=days)
            local_naive = datetime(
                local_end_date.year,
                local_end_date.month,
                local_end_date.day,
                0, 0, 0,
            )
            return tz.localize(local_naive, is_dst=None).astimezone(
                pytz.UTC).replace(tzinfo=None)
        except Exception:
            return self.air_datetime_end

    def _status_at(self, now_utc):
        """'scheduled' / 'live' / 'ended' for this record at [now_utc]."""
        self.ensure_one()
        try:
            start = self.air_datetime_start
            end = self._active_window_utc_end()
            if not start or not end or now_utc < start:
                return 'scheduled'
            if start <= now_utc <= end:
                return 'live'
            return 'ended'
        except Exception:
            return 'scheduled'

    # Stored status (refreshed by the cron) and the live-now flag use
    # separate compute methods: Odoo 19 warns when one method fills a stored
    # and a non-stored field together.
    @api.depends('air_datetime_start', 'air_datetime_end', 'play_for_days')
    def _compute_status_auto(self):
        now_utc = datetime.utcnow()
        for rec in self:
            rec.status = rec._status_at(now_utc)

    def _compute_is_live_now(self):
        now_utc = datetime.utcnow()
        for rec in self:
            rec.is_live_now = rec._status_at(now_utc) == 'live'

    # ── Cron: refresh all statuses every minute ───────────────
    def action_refresh_all_statuses(self):
        """Called by the scheduler every minute."""
        records = self.search([('is_published', '=', True)])
        now_utc = datetime.utcnow()
        for rec in records:
            start = rec.air_datetime_start
            end   = rec._active_window_utc_end()
            if not start or not end:
                new_status = 'scheduled'
            elif now_utc < start:
                new_status = 'scheduled'
            elif start <= now_utc <= end:
                new_status = 'live'
            else:
                new_status = 'ended'
            if rec.status != new_status:
                rec.write({'status': new_status})


    # ── Constraint: validate HH:MM format ────────────────────
    @api.constrains('air_time')
    def _check_air_time(self):
        import re
        for rec in self:
            if rec.air_time and not re.match(r'^\d{2}:\d{2}$', rec.air_time):
                raise ValidationError(   # ✅ from odoo.exceptions
                    'Air Time must be HH:MM format — e.g. 09:00 or 14:30'
                )
