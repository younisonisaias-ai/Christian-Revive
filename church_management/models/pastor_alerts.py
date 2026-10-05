"""Push alerts to pastors (urgent / private prayer requests, relatives added
by members, RSVPs to special events) and the device registration they need."""
import json
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _send_fcm(sa_path, tokens, title, body, data):
    """Send one FCM v1 message per token. Runs after the database commit, so it
    uses no Odoo environment — only plain Python."""
    if not sa_path or not tokens:
        return
    try:
        from google.oauth2 import service_account
        import google.auth.transport.requests as gatr
        with open(sa_path, 'r') as f:
            info = json.load(f)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/firebase.messaging'])
        creds.refresh(gatr.Request())
        url = 'https://fcm.googleapis.com/v1/projects/%s/messages:send' % info.get('project_id', '')
        headers = {'Authorization': 'Bearer %s' % creds.token, 'Content-Type': 'application/json'}
        for token in tokens:
            message = {
                'token': token,
                'notification': {'title': title, 'body': body},
                'data': {k: str(v) for k, v in dict(data, title=title, body=body).items()},
                'android': {'priority': 'high', 'notification': {'sound': 'default'}},
                'apns': {'payload': {'aps': {'sound': 'default'}}},
            }
            try:
                requests.post(url, headers=headers, data=json.dumps({'message': message}), timeout=10)
            except Exception as exc:  # one bad token must not stop the others
                _logger.warning('Pastor alert to one device failed: %s', exc)
    except Exception as exc:
        _logger.warning('Pastor alert not sent: %s', exc)


class ResPartnerDevice(models.Model):
    _inherit = 'res.partner'

    app_fcm_token = fields.Char(string='App Device Token', copy=False,
                                help='Lets the church send this member app notifications.')

    @api.model
    def app_register_member_device(self, token, requester_partner_id=None):
        mode, scope = self._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self' or not token:
            return {'success': False}
        self.sudo().browse(scope).write({'app_fcm_token': token})
        return {'success': True}


class HrEmployeeDevice(models.Model):
    _inherit = 'hr.employee'

    app_fcm_token = fields.Char(string='App Device Token', copy=False,
                                help='Phone that receives pastor alerts for this staff member.')

    @api.model
    def app_register_staff_device(self, token, requester_staff_id=None):
        employee = self.sudo().browse(int(requester_staff_id or 0)).exists()
        if not employee or not employee.is_app_active or not token:
            return {'success': False}
        employee.write({'app_fcm_token': token})
        return {'success': True}

    @api.model
    def app_unregister_staff_device(self, token, requester_staff_id=None):
        """Logout: stop sending this staff member's alerts to this phone."""
        employee = self.sudo().browse(int(requester_staff_id or 0)).exists()
        if employee and token and employee.app_fcm_token == token:
            employee.write({'app_fcm_token': False})
        return {'success': True}


class ChurchAlerts(models.AbstractModel):
    _name = 'church.alerts'
    _description = 'Pastor push alerts'

    @api.model
    def _pastors_for(self, member):
        """Pastors assigned to [member]; senior pastors when nobody is."""
        Employee = self.env['hr.employee'].sudo()
        pastors = self.env['pastor.assignment'].sudo().search(
            [('member_id', '=', member.id)]).mapped('pastor_id') if member else Employee
        if not pastors:
            pastors = Employee.search([('staff_role', '=', 'pastor'), ('is_senior_pastor', '=', True)])
        return pastors.filtered(lambda e: e.is_app_active and e.app_fcm_token)

    @api.model
    def notify_pastors(self, member, title, body, kind, record_id=0):
        pastors = self._pastors_for(member)
        tokens = list(set(pastors.mapped('app_fcm_token')))
        if not tokens:
            return
        sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
        data = {'type': 'pastor_alert', 'kind': kind, 'id': record_id}
        # Send only once the change is really saved.
        self.env.cr.postcommit.add(lambda: _send_fcm(sa_path, tokens, title, body, data))
