"""Weekly repeating services: set "Sabbath Worship, every Saturday 10:00"
once and the upcoming weeks' services are created automatically, so
check-in, RSVP and QR always have something to work with."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

WEEKDAYS = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
    ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
]
DEFAULT_TZ = 'Asia/Karachi'


class ChurchServiceSchedule(models.Model):
    _name = 'church.service.schedule'
    _description = 'Weekly Repeating Service'
    _order = 'weekday, start_time'

    name = fields.Char(string='Title', required=True, help='e.g. Sabbath Worship')
    service_type = fields.Selection(
        lambda self: self.env['church.service']._fields['service_type'].selection,
        string='Type', default='sabbath_worship', required=True)
    weekday = fields.Selection(WEEKDAYS, string='Every', required=True, default='5')
    start_time = fields.Float(string='Starts at', required=True, default=10.0,
                              help='Local church time, e.g. 10:30 = 10.5')
    duration_hours = fields.Float(string='Length (hours)', default=2.0)
    location = fields.Char(string='Location')
    weeks_ahead = fields.Integer(string='Create weeks ahead', default=4,
                                 help='How many upcoming weeks are kept ready.')
    active = fields.Boolean(default=True)
    service_ids = fields.One2many('church.service', 'schedule_id', string='Services created')
    next_date = fields.Datetime(string='Next service', compute='_compute_next_date')

    def _compute_next_date(self):
        now = fields.Datetime.now()
        for rec in self:
            upcoming = rec.service_ids.filtered(lambda s: s.date_start and s.date_start >= now)
            rec.next_date = min(upcoming.mapped('date_start')) if upcoming else False

    def _church_tz(self):
        name = self.env['ir.config_parameter'].sudo().get_param('church_management.timezone') \
            or self.env.user.tz or DEFAULT_TZ
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.timezone(DEFAULT_TZ)

    def _upcoming_starts(self, today):
        """UTC start datetimes (naive) for this schedule's next weeks."""
        self.ensure_one()
        tz = self._church_tz()
        hours = int(self.start_time)
        minutes = int(round((self.start_time - hours) * 60)) % 60
        days_until = (int(self.weekday) - today.weekday()) % 7
        first = today + timedelta(days=days_until)
        starts = []
        for week in range(max(1, min(self.weeks_ahead or 4, 12))):
            day = first + timedelta(weeks=week)
            local = tz.localize(datetime.combine(day, time(hours % 24, minutes)))
            starts.append(local.astimezone(pytz.UTC).replace(tzinfo=None))
        return starts

    def action_generate_services(self):
        """Create any missing upcoming services (safe to run any time)."""
        Service = self.env['church.service'].sudo()
        now = fields.Datetime.now()
        created = 0
        for rec in self.filtered('active'):
            today = datetime.now(rec._church_tz()).date()
            for start in rec._upcoming_starts(today):
                if start < now:
                    continue
                day_start, day_end = start - timedelta(hours=12), start + timedelta(hours=12)
                exists = Service.search_count([
                    ('schedule_id', '=', rec.id),
                    ('date_start', '>=', day_start), ('date_start', '<', day_end),
                ])
                if exists:
                    continue
                Service.create({
                    'name': rec.name,
                    'service_type': rec.service_type,
                    'date_start': start,
                    'date_end': start + timedelta(hours=rec.duration_hours or 2),
                    'location': rec.location or False,
                    'schedule_id': rec.id,
                    'is_active': True,
                })
                created += 1
        return created

    @api.model
    def _cron_generate_services(self):
        self.search([]).action_generate_services()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.action_generate_services()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'weekday', 'start_time', 'weeks_ahead', 'active'} & set(vals):
            self.action_generate_services()
        return result


class ChurchServiceFromSchedule(models.Model):
    _inherit = 'church.service'

    schedule_id = fields.Many2one('church.service.schedule', string='Weekly Schedule',
                                  ondelete='set null', index=True, readonly=True)
