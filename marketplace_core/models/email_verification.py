# -*- coding: utf-8 -*-
import secrets

from markupsafe import Markup

from odoo import _, api, fields, models

TOKEN_LIFETIME_HOURS = 48


class MarketplaceEmailVerification(models.Model):
    _name = 'marketplace.email.verification'
    _description = 'Marketplace Email Verification Token'
    _order = 'create_date desc'

    partner_id = fields.Many2one(
        'res.partner', required=True, index=True, ondelete='cascade')
    token = fields.Char(required=True, index=True)
    expires_at = fields.Datetime(required=True)
    used = fields.Boolean(default=False)

    _token_uniq = models.Constraint(
        'unique(token)',
        'Token collision - retry.',
    )

    @api.model
    def issue(self, partner):
        """Invalidate any previous unused tokens for this partner (so an
        old email link can't verify after a newer one was requested) and
        issue a fresh one."""
        self.sudo().search([
            ('partner_id', '=', partner.id), ('used', '=', False),
        ]).write({'used': True})
        return self.sudo().create({
            'partner_id': partner.id,
            'token': secrets.token_urlsafe(32),
            'expires_at': fields.Datetime.add(
                fields.Datetime.now(), hours=TOKEN_LIFETIME_HOURS),
        })

    @api.model
    def send_verification_email(self, partner, base_url):
        """Issues a fresh token and emails a verification link. Best-
        effort: a delivery failure shouldn't block registration, so
        callers should wrap this in a try/except and let signup succeed
        either way (the user can request a resend later)."""
        token = self.issue(partner)
        url = '%s/market/verify-email?token=%s' % (
            base_url.rstrip('/'), token.token)
        body = Markup(
            '<div style="font-family: Arial, sans-serif; color: #333;">'
            '<p>Hi %(name)s,</p>'
            '<p>Welcome to Bazaar! Please confirm this is your email '
            'address to finish setting up your account.</p>'
            '<p><a href="%(url)s" style="display:inline-block;padding:'
            '10px 20px;background:#0d9488;color:#fff;border-radius:8px;'
            'text-decoration:none;">Verify Email</a></p>'
            '<p style="color:#888;font-size:12px;">Or paste this link in '
            'your browser:<br/>%(url)s</p>'
            '<p style="color:#888;font-size:12px;">This link expires in '
            '48 hours. If you did not create this account, you can '
            'ignore this email.</p></div>'
        ) % {'name': partner.name or '', 'url': url}
        self.env['mail.mail'].sudo().create({
            'subject': _('Verify your email for Bazaar Marketplace'),
            'body_html': body,
            'email_from': self._default_email_from(),
            'email_to': partner.email,
            'auto_delete': True,
        }).send()
        return token

    def _default_email_from(self):
        """Providers like Gmail's SMTP relay silently reject mail whose
        From address doesn't match the authenticated account, so a blank
        or arbitrary From (mail.mail's default when none is given) fails
        delivery outright rather than erroring loudly. Use whatever
        account the configured outgoing mail server actually
        authenticates as, falling back to the company email."""
        mail_server = self.env['ir.mail_server'].sudo().search(
            [], limit=1, order='sequence')
        if mail_server and mail_server.smtp_user:
            return mail_server.smtp_user
        return self.env.company.email or False

    @api.model
    def verify(self, token_str):
        """Marks the partner verified and activates their (pending, until
        now inactive) account if the token is valid and unused. Returns
        the partner record on success, an empty recordset otherwise."""
        if not token_str:
            return self.env['res.partner']
        record = self.sudo().search([('token', '=', token_str)], limit=1)
        if not record or record.used or record.expires_at < fields.Datetime.now():
            return self.env['res.partner']
        record.used = True
        partner = record.partner_id
        partner.marketplace_email_verified = True
        users = self.env['res.users'].sudo().with_context(
            active_test=False).search([('partner_id', '=', partner.id)])
        users.write({'active': True})
        return partner
