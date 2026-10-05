# -*- coding: utf-8 -*-
"""Firebase Cloud Messaging push notifications.

Config-gated exactly like the Stripe integration: until an admin pastes a
Firebase project ID and service-account JSON into Settings, every call
here is a silent no-op — callers never need to check whether push is
configured before notifying a partner.

Implemented with plain `requests` + `cryptography` (both already present
in the Odoo image) instead of the `google-auth`/`firebase-admin` SDKs,
which aren't installed: a service-account JWT is signed by hand and
exchanged for an OAuth2 access token, then used to call FCM's HTTP v1
send endpoint directly.
"""
import base64
import json
import logging
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

TOKEN_URI = 'https://oauth2.googleapis.com/token'
FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=')


class MarketplaceDeviceToken(models.Model):
    _name = 'marketplace.device.token'
    _description = 'Mobile Push Notification Device Token'
    _rec_name = 'token'

    partner_id = fields.Many2one(
        'res.partner', required=True, index=True, ondelete='cascade')
    token = fields.Char(required=True, index=True)
    platform = fields.Selection([
        ('android', 'Android'), ('ios', 'iOS'), ('web', 'Web'),
    ], default='android')
    active = fields.Boolean(default=True)

    _token_uniq = models.Constraint(
        'unique(token)',
        'This device is already registered.',
    )

    @api.model
    def register(self, partner, token, platform=None):
        if not token:
            return
        existing = self.sudo().search([('token', '=', token)], limit=1)
        if existing:
            existing.write({
                'partner_id': partner.id, 'active': True,
                'platform': platform or existing.platform,
            })
            return existing
        return self.sudo().create({
            'partner_id': partner.id, 'token': token,
            'platform': platform or 'android',
        })

    @api.model
    def unregister(self, token):
        self.sudo().search([('token', '=', token)]).write({'active': False})


class MarketplaceFcmSender(models.AbstractModel):
    _name = 'marketplace.fcm.sender'
    _description = 'Firebase Cloud Messaging Sender'

    @api.model
    def _configured(self):
        icp = self.env['ir.config_parameter'].sudo()
        return bool(
            icp.get_param('marketplace_core.fcm_project_id')
            and icp.get_param('marketplace_core.fcm_service_account_json'))

    @api.model
    def _get_access_token(self):
        """Signs a service-account JWT and exchanges it for a short-lived
        OAuth2 access token. Returns None (never raises) on any failure
        so a misconfigured/expired key degrades to "push silently
        doesn't happen" rather than breaking the caller's real action."""
        icp = self.env['ir.config_parameter'].sudo()
        raw_json = icp.get_param('marketplace_core.fcm_service_account_json')
        try:
            account = json.loads(raw_json)
            private_key = serialization.load_pem_private_key(
                account['private_key'].encode(), password=None)
            now = int(time.time())
            header = {'alg': 'RS256', 'typ': 'JWT'}
            claims = {
                'iss': account['client_email'],
                'scope': FCM_SCOPE,
                'aud': account.get('token_uri', TOKEN_URI),
                'iat': now,
                'exp': now + 3600,
            }
            signing_input = b'.'.join([
                _b64url(json.dumps(header).encode()),
                _b64url(json.dumps(claims).encode()),
            ])
            signature = private_key.sign(
                signing_input, padding.PKCS1v15(), hashes.SHA256())
            assertion = signing_input + b'.' + _b64url(signature)
            resp = requests.post(account.get('token_uri', TOKEN_URI), data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': assertion,
            }, timeout=15)
            resp.raise_for_status()
            return resp.json()['access_token'], account['project_id']
        except Exception:
            _logger.exception('FCM: could not obtain access token')
            return None, None

    @api.model
    def notify_partner(self, partner, title, body, data=None):
        """Best-effort push to every active device of `partner`. Silently
        does nothing if FCM isn't configured or the partner has no
        registered devices — callers never need to guard this call."""
        if not self._configured():
            return
        tokens = self.env['marketplace.device.token'].sudo().search([
            ('partner_id', '=', partner.id), ('active', '=', True),
        ])
        if not tokens:
            return
        access_token, project_id = self._get_access_token()
        if not access_token:
            return
        url = ('https://fcm.googleapis.com/v1/projects/%s/messages:send'
               % project_id)
        headers = {
            'Authorization': 'Bearer %s' % access_token,
            'Content-Type': 'application/json',
        }
        for device in tokens:
            message = {
                'message': {
                    'token': device.token,
                    'notification': {'title': title, 'body': body},
                    'data': {k: str(v) for k, v in (data or {}).items()},
                }
            }
            try:
                resp = requests.post(
                    url, headers=headers, json=message, timeout=15)
                if resp.status_code == 404:
                    # Token no longer valid (app uninstalled, etc.)
                    device.active = False
                elif resp.status_code >= 400:
                    _logger.warning('FCM send failed for device %s: %s',
                                    device.id, resp.text)
            except requests.RequestException:
                _logger.exception('FCM send failed for device %s', device.id)
