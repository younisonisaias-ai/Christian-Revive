# -*- coding: utf-8 -*-
from odoo import fields, models


class LifestyleStockNotification(models.Model):
    """Captures "notify me when back in stock" signups from the website so
    admins can follow up manually once a product is restocked."""
    _name = 'lifestyle.stock.notification'
    _description = 'Revive Lifestyle Stock Notification Request'
    _order = 'create_date desc'

    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    email = fields.Char(string='Email', required=True)
    notified = fields.Boolean(string='Notified', default=False)

    _notification_unique = models.Constraint(
        'unique(product_tmpl_id, email)',
        'This email is already on the notify list for this product.',
    )

    def action_mark_notified(self):
        self.write({'notified': True})
