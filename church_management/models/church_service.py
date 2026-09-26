from datetime import timedelta

from odoo import models, fields, api


class ChurchService(models.Model):
    """A church service or event that people can be checked in to
    (Sabbath worship, Sabbath School, prayer meeting, youth, ...).

    Owned by Church Management so attendance no longer depends on the
    OneVoice27 events module.
    """
    _name = 'church.service'
    _description = 'Church Service / Event'
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Title', required=True)
    service_type = fields.Selection([
        ('sabbath_worship', 'Sabbath Worship'),
        ('sabbath_school', 'Sabbath School'),
        ('prayer_meeting', 'Prayer Meeting'),
        ('bible_study', 'Bible Study'),
        ('youth', 'Youth'),
        ('children', 'Children'),
        ('small_group', 'Small Group'),
        ('special_event', 'Special Event'),
        ('other', 'Other'),
    ], string='Type', default='sabbath_worship', required=True)
    date_start = fields.Datetime(string='Starts', required=True, default=fields.Datetime.now)
    date_end = fields.Datetime(string='Ends')
    location = fields.Char(string='Location')
    description = fields.Text(string='Description')
    is_active = fields.Boolean(
        string='Open for Check-in', default=True,
        help='Only active services are offered for check-in in the app.')
    attendance_ids = fields.One2many('church.event.attendance', 'event_id', string='Attendance')
    attendance_count = fields.Integer(string='Checked In', compute='_compute_attendance_count')
    # Set only for services created from old OneVoice27 events during the
    # migration, so older app versions that still send OneVoice event ids keep
    # checking people in to the right service.
    legacy_onevoice_event_id = fields.Integer(string='Legacy OneVoice Event', index=True, readonly=True)

    @api.depends('attendance_ids')
    def _compute_attendance_count(self):
        for rec in self:
            rec.attendance_count = len(rec.attendance_ids)

    def action_view_attendance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance',
            'res_model': 'church.event.attendance',
            'view_mode': 'list,form',
            'domain': [('event_id', '=', self.id)],
            'context': {'default_event_id': self.id},
        }

    # ── Flutter app RPC ─────────────────────────────────────────

    @api.model
    def app_get_services(self, requester_partner_id=None, requester_staff_id=None,
                         days_back=7, days_ahead=30):
        """Active services from `days_back` days ago to `days_ahead` days ahead,
        soonest first — what the Check-In screen offers."""
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}
        now = fields.Datetime.now()
        records = self.sudo().search([
            ('is_active', '=', True),
            ('date_start', '>=', now - timedelta(days=days_back or 0)),
            ('date_start', '<=', now + timedelta(days=days_ahead or 0)),
        ], order='date_start asc, id asc')
        type_labels = dict(self._fields['service_type'].selection)
        return {'success': True, 'services': [{
            'id': r.id,
            'name': r.name,
            'service_type': r.service_type,
            'service_type_label': type_labels.get(r.service_type, ''),
            'date_start': fields.Datetime.to_string(r.date_start) if r.date_start else False,
            'date_end': fields.Datetime.to_string(r.date_end) if r.date_end else False,
            'location': r.location or '',
            'attendance_count': r.attendance_count,
        } for r in records]}

    @api.model
    def _from_legacy_onevoice_event(self, onevoice_event_id):
        """Church service standing in for an old OneVoice27 event id, created on
        first use. Used only by older app versions."""
        service = self.sudo().search(
            [('legacy_onevoice_event_id', '=', onevoice_event_id)], limit=1)
        if service:
            return service
        vals = {
            'name': 'Event #%s' % onevoice_event_id,
            'service_type': 'special_event',
            'legacy_onevoice_event_id': onevoice_event_id,
            'is_active': False,
        }
        # onevoice27 is no longer a dependency; read the old event only if
        # that module happens to be installed.
        if 'onevoice.event' in self.env:
            event = self.env['onevoice.event'].sudo().browse(onevoice_event_id).exists()
            if event:
                vals['name'] = event.name or vals['name']
                if event.date_start:
                    vals['date_start'] = event.date_start
                if 'location' in event._fields and event.location:
                    vals['location'] = event.location
        return self.sudo().create(vals)
