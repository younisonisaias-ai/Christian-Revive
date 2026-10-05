# -*- coding: utf-8 -*-
from odoo import fields, models


class LifestyleWishlistItem(models.Model):
    """A product a customer saved for later in the Revive Lifestyle app."""
    _name = 'lifestyle.wishlist.item'
    _description = 'Revive Lifestyle Wishlist Item'
    _order = 'create_date desc'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True, ondelete='cascade', index=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)

    _wishlist_unique = models.Constraint(
        'unique(partner_id, product_tmpl_id)',
        'This product is already in the wishlist.',
    )
