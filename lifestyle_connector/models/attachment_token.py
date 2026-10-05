# -*- coding: utf-8 -*-
import secrets

from odoo import models, fields, api


class LifestyleAttachmentToken(models.Model):
    """A random, unguessable token granting public read access to exactly one
    attachment, so a vendor photo can be embedded as an image URL in a push
    notification without exposing Odoo session/admin credentials."""
    _name = 'lifestyle.attachment.token'
    _description = 'Public Attachment Access Token'

    attachment_id = fields.Many2one('ir.attachment', string='Attachment', required=True, ondelete='cascade')
    token = fields.Char(string='Token', required=True, index=True, default=lambda self: secrets.token_urlsafe(24))

    _token_unique = models.Constraint(
        'unique(token)',
        'Token must be unique.',
    )

    @api.model
    def grant(self, attachment):
        existing = self.search([('attachment_id', '=', attachment.id)], limit=1)
        return existing or self.create({'attachment_id': attachment.id})
