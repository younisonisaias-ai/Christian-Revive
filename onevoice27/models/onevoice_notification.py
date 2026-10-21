# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OneVoiceNotification(models.Model):
    _name        = 'onevoice.notification'
    _description = 'OneVoice27 Push Notification'
    _order       = 'create_date desc'
    _rec_name    = 'title'

    title       = fields.Char(string='Title',   required=True)
    message     = fields.Text(string='Message', required=True)
    target      = fields.Selection([
        ('all',    'All OneVoice27 Users'),
        ('device', 'Specific Device'),
    ], string='Send To', required=True, default='all')
    device_id   = fields.Many2one(
        'onevoice.device', string='Device',
        domain=[],
        help='Required when "Send To" is set to Specific Device',
    )
    status      = fields.Selection([
        ('draft', 'Draft'),
        ('sent',  'Sent'),
        ('error', 'Error'),
    ], string='Status', default='draft', readonly=True)
    sent_at     = fields.Datetime(string='Sent At', readonly=True)
    error_msg   = fields.Text(string='Error Detail', readonly=True)
    sent_count  = fields.Integer(string='Devices Reached', readonly=True, default=0)

    # ── Constraints ─────────────────────────────────────────────
    @api.constrains('target', 'device_id')
    def _check_device(self):
        for rec in self:
            if rec.target == 'device' and not rec.device_id:
                raise UserError('Please select a device when "Send To" is Specific Device.')

    # ── Send action ─────────────────────────────────────────────
    def action_send(self):
        self.ensure_one()
        if self.status == 'sent':
            raise UserError('This notification has already been sent.')

        access_token, project_id = self._get_fcm_credentials()

        if self.target == 'all':
            self._send_to_topic(access_token, project_id)
        else:
            self._send_to_device(access_token, project_id)

    # ── Load service-account credentials ────────────────────────
    def _get_fcm_credentials(self):
        sa_path = self.env['ir.config_parameter'].sudo().get_param(
            'onevoice27.fcm_service_account_path', ''
        )
        if not sa_path:
            raise UserError(
                'FCM Service Account not configured.\n\n'
                'Go to Settings → Technical → System Parameters and add:\n'
                '  Key:   onevoice27.fcm_service_account_path\n'
                '  Value: /path/to/your/service-account.json\n\n'
                'Download the JSON from Firebase Console → Project Settings → Service Accounts.'
            )
        try:
            from google.oauth2 import service_account
            import google.auth.transport.requests as gatr

            with open(sa_path, 'r') as f:
                sa_info = json.load(f)

            project_id = sa_info.get('project_id', '')
            if not project_id:
                raise UserError('project_id not found in service account JSON.')

            creds = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=['https://www.googleapis.com/auth/firebase.messaging'],
            )
            creds.refresh(gatr.Request())
            return creds.token, project_id

        except ImportError:
            raise UserError(
                'The google-auth library is not installed on the server.\n\n'
                'Run:  pip install google-auth'
            )
        except UserError:
            raise
        except Exception as exc:
            raise UserError(f'Failed to load FCM credentials: {exc}')

    # ── Build FCM v1 message payload ────────────────────────────
    def _build_payload(self, token=None, topic=None):
        message = {
            'notification': {
                'title': self.title,
                'body':  self.message,
            },
            'data': {
                'type':     'ov27_push',
                'title':    self.title,
                'body':     self.message,
                'notif_id': str(self.id),
            },
            'android': {
                'priority': 'high',
                'notification': {
                    'sound': 'default',
                },
            },
            'apns': {
                'payload': {
                    'aps': {
                        'sound': 'default',
                        'content-available': 1,
                    },
                },
            },
        }
        if topic:
            message['topic'] = topic
        elif token:
            message['token'] = token
        return {'message': message}

    # ── POST to FCM v1 API ───────────────────────────────────────
    def _fcm_post(self, access_token, project_id, payload):
        url = f'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type':  'application/json',
        }
        try:
            resp = requests.post(
                url, headers=headers,
                data=json.dumps(payload), timeout=15,
            )
            resp.raise_for_status()
            result = resp.json()
            _logger.info('FCM v1 response: %s', result)
            return result
        except Exception as exc:
            _logger.error('FCM v1 send failed: %s', exc)
            raise

    # ── Send to topic (all users) ────────────────────────────────
    def _send_to_topic(self, access_token, project_id):
        # Each church's app listens on its own prefix (Settings → Church).
        prefix = self.env['ir.config_parameter'].sudo().get_param('revive.topic_prefix') or 'revive'
        payload = self._build_payload(topic='%s_ov27' % prefix)
        try:
            self._fcm_post(access_token, project_id, payload)
            self.write({
                'status':     'sent',
                'sent_at':    fields.Datetime.now(),
                'sent_count': 1,
                'error_msg':  False,
            })
        except Exception as exc:
            self.write({'status': 'error', 'error_msg': str(exc)})
            raise UserError(f'FCM send failed: {exc}')

    # ── Send to a specific device ────────────────────────────────
    def _send_to_device(self, access_token, project_id):
        token = self.device_id.fcm_token
        if not token:
            raise UserError('Selected device has no FCM token.')
        payload = self._build_payload(token=token)
        try:
            result = self._fcm_post(access_token, project_id, payload)
            success = 'name' in result  # v1 returns {"name": "projects/.../messages/..."}
            self.write({
                'status':     'sent' if success else 'error',
                'sent_at':    fields.Datetime.now(),
                'sent_count': 1 if success else 0,
                'error_msg':  False if success else json.dumps(result),
            })
            if not success:
                raise UserError(f'FCM rejected the token: {result}')
        except UserError:
            raise
        except Exception as exc:
            self.write({'status': 'error', 'error_msg': str(exc)})
            raise UserError(f'FCM send failed: {exc}')

    def action_reset_draft(self):
        self.ensure_one()
        self.write({'status': 'draft', 'error_msg': False})
