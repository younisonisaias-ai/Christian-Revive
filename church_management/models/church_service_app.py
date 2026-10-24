"""Services & events from the staff app: list, create, edit and cancel.

Only the admin and senior pastor may change them (the same people who mark
church locations). One-off services only; weekly schedules stay in the ERP.
"""
import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Fields the app may set, with the switches defaulting as in the ERP.
_SWITCHES = ('smart_checkin_enabled', 'geofence_required', 'notify_on_arrival')


def _parse_utc(value):
    """'YYYY-MM-DD HH:MM:SS' (UTC) from the app, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None


class ChurchServiceApp(models.Model):
    _inherit = 'church.service'

    def _app_dict(self):
        self.ensure_one()
        return dict(
            self._local_labels(),
            service_id=self.id,
            name=self.name,
            service_type=self.service_type,
            date_start=fields.Datetime.to_string(self.date_start),
            date_end=fields.Datetime.to_string(self.date_end) if self.date_end else False,
            location_id=self.location_id.id or False,
            location_name=self.location_id.name or self.location or '',
            description=self.description or '',
            cancelled=self.cancelled,
            checked_in=self.attendance_count,
            **{k: self[k] for k in _SWITCHES},
        )

    @api.model
    def app_admin_services(self, days_back=1, days_ahead=90):
        """Services from yesterday on, for the staff Services & Events screen."""
        staff, may_edit = self.env['church.location']._app_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        now = fields.Datetime.now()
        services = self.sudo().search([
            ('date_start', '>=', now - timedelta(days=max(0, int(days_back or 0)))),
            ('date_start', '<=', now + timedelta(days=max(1, min(int(days_ahead or 90), 366)))),
        ], order='date_start asc, id asc', limit=200)
        types = self._fields['service_type'].selection
        return {
            'success': True,
            'can_edit': may_edit,
            'types': [{'key': k, 'label': v} for k, v in types],
            'services': [s._app_dict() for s in services],
        }

    @api.model
    def app_save_service(self, vals, service_id=None, notify=False):
        """Creates or updates a one-off service. notify: push to all members."""
        _staff, may_edit = self.env['church.location']._app_staff()
        if not may_edit:
            return {'success': False, 'error': 'Only the church admin or senior pastor can add or change events.'}
        vals = vals or {}
        name = ' '.join(str(vals.get('name') or '').split())
        start = _parse_utc(vals.get('date_start'))
        end = _parse_utc(vals.get('date_end'))
        if not name:
            return {'success': False, 'error': 'Give the event a title.'}
        if not start:
            return {'success': False, 'error': 'Choose when the event starts.'}
        if end and end <= start:
            return {'success': False, 'error': 'The end time must be after the start time.'}
        types = dict(self._fields['service_type'].selection)
        write = {
            'name': name,
            'date_start': start,
            'date_end': end or False,
            'description': str(vals.get('description') or '').strip() or False,
        }
        if vals.get('service_type') in types:
            write['service_type'] = vals['service_type']
        if 'location_id' in vals:
            location = self.env['church.location'].sudo().browse(int(vals['location_id'] or 0)).exists()
            if vals['location_id'] and not location:
                return {'success': False, 'error': 'That place no longer exists.'}
            write['location_id'] = location.id or False
        for key in _SWITCHES:
            if key in vals:
                write[key] = bool(vals[key])
        if service_id:
            service = self.sudo().browse(int(service_id)).exists()
            if not service:
                return {'success': False, 'error': 'This event no longer exists.'}
            service.write(write)
        else:
            service = self.sudo().create(dict(write, is_active=True, attendance_enabled=True))
        sent = service._app_notify_members() if notify else False
        return {'success': True, 'service': service._app_dict(), 'notified': sent}

    @api.model
    def app_cancel_service(self, service_id, cancelled=True):
        """Cancels an event (members can no longer check in), or brings it back."""
        _staff, may_edit = self.env['church.location']._app_staff()
        if not may_edit:
            return {'success': False, 'error': 'Only the church admin or senior pastor can cancel events.'}
        service = self.sudo().browse(int(service_id or 0)).exists()
        if not service:
            return {'success': False, 'error': 'This event no longer exists.'}
        service.cancelled = bool(cancelled)
        return {'success': True, 'service': service._app_dict()}

    def _app_notify_members(self):
        """Sends one push to every app user about this event. True when sent."""
        self.ensure_one()
        labels = self._local_labels()
        when = ' · '.join(p for p in (labels.get('date_label'), labels.get('time_label')) if p)
        place = self.location_id.name or self.location or ''
        message = ' – '.join(p for p in (when, place) if p) or 'Open the app for details.'
        try:
            note = self.env['revive.notification'].sudo().create({
                'title': self.name, 'message': message, 'target': 'all'})
            note.action_send()
            return True
        except Exception as exc:  # noqa: BLE001 - the event is saved either way
            _logger.warning('Event notification not sent for service %s: %s', self.id, exc)
            return False
