"""Church locations from the staff app: mark the spot where you stand.

The admin or senior pastor stands at the church, the app reads the phone's
GPS, and the latitude, longitude and check-in radius are saved on the same
church.location the ERP shows. Any staff member may list locations; only the
admin and senior pastor may add, move or assign them.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from . import attendance_rules as rules


def _location_dict(loc):
    return {
        'location_id': loc.id,
        'name': loc.name,
        'address': loc.address or '',
        'latitude': loc.latitude if loc._has_coordinates() else None,
        'longitude': loc.longitude if loc._has_coordinates() else None,
        'radius_m': loc.geofence_radius_m,
        'verify': loc.location_validation_enabled,
        'reminders': loc.geofence_enabled,
        'write_date': fields.Datetime.to_string(loc.write_date),
    }


class ChurchLocationApp(models.Model):
    _inherit = 'church.location'

    @api.model
    def _app_staff(self):
        """(staff, may_edit) for this request's staff session."""
        session = self.env['church.app.session']._current_staff()
        staff = session.employee_id if session else self.env['hr.employee']
        if not staff or not staff.is_app_active:
            return self.env['hr.employee'], False
        may_edit = staff.staff_role == 'admin' or (staff.staff_role == 'pastor' and staff.is_senior_pastor)
        return staff, may_edit

    @api.model
    def app_church_locations(self):
        staff, may_edit = self._app_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        locations = self.sudo().search([('active', '=', True)], order='sequence, name')
        return {'success': True, 'can_edit': may_edit, 'locations': [_location_dict(l) for l in locations]}

    @api.model
    def app_save_church_location(self, vals, location_id=None):
        """Adds or updates a location: name, address, latitude, longitude, radius_m."""
        _staff, may_edit = self._app_staff()
        if not may_edit:
            return {'success': False, 'error': 'Only the church admin or senior pastor can change church locations.'}
        vals = vals or {}
        name = ' '.join(str(vals.get('name') or '').split())
        try:
            lat, lon = float(vals['latitude']), float(vals['longitude'])
            radius = int(vals.get('radius_m') or rules.DEFAULT_RADIUS_M)
        except (KeyError, TypeError, ValueError):
            return {'success': False, 'error': 'Mark the location on the map first.'}
        if not rules.valid_coordinates(lat, lon):
            return {'success': False, 'error': 'That location is not valid. Mark it again.'}
        if not 10 <= radius <= 5000:
            return {'success': False, 'error': 'The check-in radius must be between 10 and 5,000 metres.'}
        write = {'latitude': lat, 'longitude': lon, 'geofence_radius_m': radius,
                 'address': str(vals.get('address') or '').strip() or False}
        if name:
            write['name'] = name
        try:
            if location_id:
                location = self.sudo().browse(int(location_id)).exists()
                if not location:
                    return {'success': False, 'error': 'This location no longer exists.'}
                location.write(write)
            else:
                if not name:
                    return {'success': False, 'error': 'Give the location a name.'}
                location = self.sudo().create(dict(write, location_validation_enabled=True, geofence_enabled=True))
        except ValidationError as e:
            return {'success': False, 'error': str(e.args[0] if e.args else e)}
        return {'success': True, 'location': _location_dict(location)}

    @api.model
    def app_location_services(self, days_ahead=60):
        """Upcoming services with where each happens, for choosing a place."""
        staff, may_edit = self._app_staff()
        if not staff:
            return {'success': False, 'error': 'Not authorized'}
        now = fields.Datetime.now()
        services = self.env['church.service'].sudo().search([
            ('date_start', '>=', now - timedelta(hours=12)),
            ('date_start', '<=', now + timedelta(days=max(1, min(int(days_ahead or 60), 366)))),
            ('cancelled', '=', False),
        ], order='date_start asc, id asc', limit=100)
        return {'success': True, 'can_edit': may_edit, 'services': [{
            'service_id': s.id, 'name': s.name,
            'date_start': fields.Datetime.to_string(s.date_start),
            'location_id': s.location_id.id or False,
            'location_name': s.location_id.name or '',
            **s._local_labels(),
        } for s in services]}

    @api.model
    def app_set_service_location(self, service_id, location_id):
        """Sets where one service happens (location_id False clears it)."""
        _staff, may_edit = self._app_staff()
        if not may_edit:
            return {'success': False, 'error': 'Only the church admin or senior pastor can change where a service is.'}
        service = self.env['church.service'].sudo().browse(int(service_id or 0)).exists()
        if not service:
            return {'success': False, 'error': 'This service is not available.'}
        location = self.sudo().browse(int(location_id)).exists() if location_id else self.browse()
        if location_id and not location:
            return {'success': False, 'error': 'This location no longer exists.'}
        service.location_id = location
        return {'success': True, 'service_id': service.id, 'location_id': location.id or False,
                'location_name': location.name or ''}
