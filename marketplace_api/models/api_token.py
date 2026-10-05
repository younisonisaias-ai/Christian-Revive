# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models


TOKEN_LIFETIME_DAYS = 90


class MarketplaceApiToken(models.Model):
    _name = 'marketplace.api.token'
    _description = 'Mobile API Access Token'
    _order = 'create_date desc'

    user_id = fields.Many2one(
        'res.users', required=True, index=True, ondelete='cascade')
    token = fields.Char(required=True, index=True)
    expires_at = fields.Datetime(required=True)
    last_used_at = fields.Datetime()
    device_name = fields.Char()

    _token_uniq = models.Constraint(
        'unique(token)',
        'Token collision — retry.',
    )

    @api.model
    def issue(self, user, device_name=None):
        return self.sudo().create({
            'user_id': user.id,
            'token': secrets.token_hex(32),
            'expires_at': fields.Datetime.add(
                fields.Datetime.now(), days=TOKEN_LIFETIME_DAYS),
            'device_name': device_name or False,
        })

    @api.model
    def resolve(self, token_str):
        """Return the res.users record for a valid token, else empty set."""
        if not token_str:
            return self.env['res.users']
        token = self.sudo().search([('token', '=', token_str)], limit=1)
        if not token or token.expires_at < fields.Datetime.now():
            return self.env['res.users']
        if not token.user_id.active:
            return self.env['res.users']
        now = fields.Datetime.now()
        # The app fires several requests in parallel on the same token
        # (e.g. loading a grid of images, or a screen's Future.wait
        # calls) — writing this bookkeeping field on every single one
        # made concurrent requests race to UPDATE the same row, which
        # Postgres resolves by aborting the loser with a serialization
        # failure. Only needed for "last seen ~when", so throttling it
        # to once a minute removes the contention instead of chasing it
        # with retries.
        if (not token.last_used_at
                or (now - token.last_used_at).total_seconds() > 60):
            token.write({'last_used_at': now})
        return token.user_id

    @api.model
    def revoke(self, token_str):
        self.sudo().search([('token', '=', token_str)]).unlink()

    @api.model
    def _cron_purge_expired(self):
        self.sudo().search([
            ('expires_at', '<', fields.Datetime.now())]).unlink()
