"""Repeating services: set "Sabbath Worship, every Saturday 10:00" once and
the upcoming services are created automatically, so check-in, RSVP and QR
always have something to work with. Services can repeat every week, every
two weeks, or once a month (e.g. the first Sunday, for communion)."""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

WEEKDAYS = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'), ('3', 'Thursday'),
    ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
]
DEFAULT_TZ = 'Asia/Karachi'
FREQUENCIES = [('weekly', 'Every week'), ('fortnightly', 'Every 2 weeks'), ('monthly', 'Once a month')]
MONTH_WEEKS = [('1', 'First'), ('2', 'Second'), ('3', 'Third'), ('4', 'Fourth'), ('last', 'Last')]


class ChurchServiceSchedule(models.Model):
    _name = 'church.service.schedule'
    _description = 'Weekly Repeating Service'
    _order = 'weekday, start_time'

    name = fields.Char(string='Title', required=True, help='e.g. Sabbath Worship')
    service_type = fields.Selection(
        lambda self: self.env['church.service']._fields['service_type'].selection,
        string='Type', default='sabbath_worship', required=True)
    weekday = fields.Selection(WEEKDAYS, string='Every', required=True, default='5')
    frequency = fields.Selection(FREQUENCIES, string='Repeats', required=True, default='weekly')
    month_week = fields.Selection(MONTH_WEEKS, string='Which week of the month', default='1',
                                  help='For services held once a month, e.g. the first Sunday.')
    start_date = fields.Date(string='Starting from', default=fields.Date.context_today,
                             help='Every-2-weeks services count from the first one on or after this date.')
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

    def _upcoming_days(self, today):
        """Local dates of this schedule's services from today on."""
        self.ensure_one()
        weekday = int(self.weekday)
        horizon = today + timedelta(weeks=max(1, min(self.weeks_ahead or 4, 12)))
        if self.frequency == 'monthly':
            # At least the next two months, so a monthly service is always ready.
            horizon = max(horizon, today + timedelta(days=62))
            days, year, month = [], today.year, today.month
            while True:
                day = self._nth_weekday(year, month, weekday, self.month_week or '1')
                if day > horizon:
                    return days
                if day >= today:
                    days.append(day)
                year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        step = 14 if self.frequency == 'fortnightly' else 7
        anchor = self.start_date or today
        anchor += timedelta(days=(weekday - anchor.weekday()) % 7)
        first = anchor if anchor >= today else             anchor + timedelta(days=-(-(today - anchor).days // step) * step)
        days, day = [], first
        while day <= horizon:
            days.append(day)
            day += timedelta(days=step)
        return days or [first]

    @staticmethod
    def _nth_weekday(year, month, weekday, which):
        """The first/second/.../last [weekday] of a month."""
        if which == 'last':
            nxt = datetime(year + (month == 12), month % 12 + 1, 1).date()
            day = nxt - timedelta(days=1)
            return day - timedelta(days=(day.weekday() - weekday) % 7)
        first = datetime(year, month, 1).date()
        first += timedelta(days=(weekday - first.weekday()) % 7)
        return first + timedelta(weeks=int(which) - 1)

    def _upcoming_starts(self, today):
        """UTC start datetimes (naive) for this schedule's coming services."""
        self.ensure_one()
        tz = self._church_tz()
        hours = int(self.start_time)
        minutes = int(round((self.start_time - hours) * 60)) % 60
        return [tz.localize(datetime.combine(day, time(hours % 24, minutes))).astimezone(pytz.UTC)
                .replace(tzinfo=None) for day in self._upcoming_days(today)]

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
        if {'weekday', 'start_time', 'weeks_ahead', 'active', 'frequency', 'month_week', 'start_date'} & set(vals):
            self.action_generate_services()
        return result


class ChurchServiceFromSchedule(models.Model):
    _inherit = 'church.service'

    schedule_id = fields.Many2one('church.service.schedule', string='Weekly Schedule',
                                  ondelete='set null', index=True, readonly=True)
