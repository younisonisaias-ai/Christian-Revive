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
    rsvp_ids = fields.One2many('church.service.rsvp', 'service_id', string='RSVPs')
    rsvp_going = fields.Integer(string='Coming', compute='_compute_rsvp_counts',
                                help='Members who said they are coming.')
    rsvp_guests = fields.Integer(string='Guests', compute='_compute_rsvp_counts',
                                 help='Extra people they are bringing.')
    rsvp_maybe = fields.Integer(string='Maybe', compute='_compute_rsvp_counts')
    rsvp_expected = fields.Integer(string='Expected', compute='_compute_rsvp_counts',
                                   help='Coming + their guests.')
    # Set only for services created from old OneVoice27 events during the
    # migration, so older app versions that still send OneVoice event ids keep
    # checking people in to the right service.
    legacy_onevoice_event_id = fields.Integer(string='Legacy OneVoice Event', index=True, readonly=True)

    @api.depends('attendance_ids')
    def _compute_attendance_count(self):
        for rec in self:
            rec.attendance_count = len(rec.attendance_ids)

    @api.depends('rsvp_ids.status', 'rsvp_ids.guests')
    def _compute_rsvp_counts(self):
        for rec in self:
            going = rec.rsvp_ids.filtered(lambda r: r.status == 'going')
            rec.rsvp_going = len(going)
            rec.rsvp_guests = sum(going.mapped('guests'))
            rec.rsvp_maybe = len(rec.rsvp_ids.filtered(lambda r: r.status == 'maybe'))
            rec.rsvp_expected = rec.rsvp_going + rec.rsvp_guests

    def _rsvp_summary(self, partner_id=None):
        self.ensure_one()
        mine = self.rsvp_ids.filtered(lambda r: r.partner_id.id == partner_id) if partner_id else None
        return {
            'my_rsvp': mine[0].status if mine else '',
            'my_guests': mine[0].guests if mine else 0,
            'rsvp_going': self.rsvp_going,
            'rsvp_guests': self.rsvp_guests,
            'rsvp_maybe': self.rsvp_maybe,
            'rsvp_expected': self.rsvp_expected,
        }

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
        partner_id = _scope if mode == 'self' else None
        return {'success': True, 'services': [dict({
            'id': r.id,
            'name': r.name,
            'service_type': r.service_type,
            'service_type_label': type_labels.get(r.service_type, ''),
            'date_start': fields.Datetime.to_string(r.date_start) if r.date_start else False,
            'date_end': fields.Datetime.to_string(r.date_end) if r.date_end else False,
            'location': r.location or '',
            'attendance_count': r.attendance_count,
        }, **r._rsvp_summary(partner_id)) for r in records]}

    # ── RSVP ("I am coming") ────────────────────────────────────

    @api.model
    def app_set_rsvp(self, service_id, status, guests=0, requester_partner_id=None):
        """A member says whether they are coming. status: going / maybe /
        not_going, or empty to clear their answer."""
        mode, scope = self.env['res.partner']._church_caller_scope(
            requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Please log in as a member'}
        service = self.sudo().browse(int(service_id)).exists()
        if not service:
            return {'success': False, 'error': 'Service not found'}
        Rsvp = self.env['church.service.rsvp'].sudo()
        existing = Rsvp.search([('service_id', '=', service.id), ('partner_id', '=', scope)], limit=1)
        if status not in ('going', 'maybe', 'not_going'):
            existing.unlink()
        else:
            count = max(0, min(int(guests or 0), 20)) if status == 'going' else 0
            vals = {'status': status, 'guests': count}
            is_new_yes = status == 'going' and (not existing or existing.status != 'going')
            if existing:
                existing.write(vals)
            else:
                Rsvp.create(dict(vals, service_id=service.id, partner_id=scope))
            # Special events: let the member's pastor know who is coming.
            if is_new_yes and service.service_type == 'special_event':
                member = self.env['res.partner'].sudo().browse(scope)
                extra = f' (+{count} guests)' if count else ''
                self.env['church.alerts'].notify_pastors(
                    member, f'🎉 {service.name}', f'{member.name} is coming{extra}',
                    'rsvp', service.id)
        return dict({'success': True}, **service._rsvp_summary(scope))

    @api.model
    def app_get_rsvps(self, service_id, requester_staff_id=None):
        """Who said they are coming (for pastors and ushers)."""
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        service = self.sudo().browse(int(service_id)).exists()
        if not service:
            return {'success': False, 'error': 'Service not found'}
        checked_in = set(service.attendance_ids.mapped('member_id').ids)
        rows = service.rsvp_ids.sorted(lambda r: (r.status != 'going', r.partner_id.name or ''))
        return dict({'success': True, 'rsvps': [{
            'partner_id': r.partner_id.id,
            'name': r.partner_id.name or '',
            'status': r.status,
            'guests': r.guests,
            'checked_in': r.partner_id.id in checked_in,
        } for r in rows]}, **service._rsvp_summary())


class ChurchServiceRsvp(models.Model):
    _name = 'church.service.rsvp'
    _description = 'Service RSVP'
    _order = 'service_id, status, partner_id'

    service_id = fields.Many2one('church.service', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Member', required=True,
                                 ondelete='cascade', index=True)
    status = fields.Selection([
        ('going', 'Coming'),
        ('maybe', 'Maybe'),
        ('not_going', 'Cannot come'),
    ], required=True, default='going')
    guests = fields.Integer(string='Bringing guests', default=0)

    _service_partner_uniq = models.Constraint(
        'unique(service_id, partner_id)',
        'Each member answers once per service.',
    )

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
