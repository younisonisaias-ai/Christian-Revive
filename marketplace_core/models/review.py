# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MarketplaceReview(models.Model):
    _name = 'marketplace.review'
    _description = 'Marketplace Review'
    _order = 'create_date desc'

    order_id = fields.Many2one(
        'sale.order', required=True, ondelete='cascade', index=True)
    seller_id = fields.Many2one(
        'marketplace.seller', required=True, ondelete='cascade', index=True)
    reviewer_id = fields.Many2one(
        'res.partner', string='Reviewer', required=True, index=True)
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], required=True)
    comment = fields.Text()
    state = fields.Selection([
        ('published', 'Published'),
        ('hidden', 'Hidden'),
    ], default='published', required=True)

    _order_reviewer_uniq = models.Constraint(
        'unique(order_id, reviewer_id)',
        'You have already reviewed this order.',
    )

    @api.constrains('order_id', 'reviewer_id')
    def _check_reviewer(self):
        for review in self:
            if review.order_id.partner_id != review.reviewer_id:
                raise ValidationError(_(
                    'Only the buyer of the order can leave a review.'))

    @api.model
    def create_for_order(self, order, partner, rating, comment=None):
        if order.partner_id != partner:
            raise UserError(_('You can only review your own orders.'))
        if order.marketplace_delivery_state != 'delivered':
            raise UserError(_(
                'You can review an order once it has been delivered.'))
        return self.sudo().create({
            'order_id': order.id,
            'seller_id': order.marketplace_seller_id.id,
            'reviewer_id': partner.id,
            'rating': str(int(rating)),
            'comment': comment or False,
        })

    def action_hide(self):
        self.write({'state': 'hidden'})

    def action_publish(self):
        self.write({'state': 'published'})
