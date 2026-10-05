# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LifestyleProductReview(models.Model):
    """A customer's star rating + comment on a product, submitted from the
    Revive Lifestyle app. product.template's store_rating/store_review_count
    are computed from these (see product_template.py) instead of being typed
    in by hand."""
    _name = 'lifestyle.product.review'
    _description = 'Revive Lifestyle Product Review'
    _order = 'create_date desc'

    product_tmpl_id = fields.Many2one('product.template', string='Product', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, ondelete='cascade')
    rating = fields.Integer(string='Rating', required=True)
    comment = fields.Text(string='Comment')

    @api.model
    def _dedupe_for_product_partner(self, product_tmpl_id, partner_id):
        reviews = self.search([
            ('product_tmpl_id', '=', product_tmpl_id),
            ('partner_id', '=', partner_id),
        ], order='write_date desc, create_date desc, id desc')
        if len(reviews) > 1:
            reviews[1:].unlink()
        return reviews[:1]

    @api.model
    def _dedupe_duplicate_reviews(self, product_tmpl_id=None):
        domain = []
        if product_tmpl_id:
            domain.append(('product_tmpl_id', '=', product_tmpl_id))
        groups = self.read_group(
            domain,
            ['product_tmpl_id', 'partner_id', '__count'],
            ['product_tmpl_id', 'partner_id'],
            lazy=False,
        )
        for group in groups:
            if group.get('__count', 0) <= 1:
                continue
            product = group.get('product_tmpl_id')
            partner = group.get('partner_id')
            if product and partner:
                self._dedupe_for_product_partner(product[0], partner[0])

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        for vals in vals_list:
            product_tmpl_id = vals.get('product_tmpl_id')
            partner_id = vals.get('partner_id')
            if product_tmpl_id and partner_id:
                existing = self._dedupe_for_product_partner(product_tmpl_id, partner_id)
                if existing:
                    existing.write({
                        key: vals[key]
                        for key in ('rating', 'comment')
                        if key in vals
                    })
                    records |= existing
                    continue
            records |= super(LifestyleProductReview, self).create([vals])
        return records

    _rating_range = models.Constraint(
        'CHECK(rating >= 1 AND rating <= 5)',
        'Rating must be between 1 and 5.',
    )
    _one_review_per_customer = models.Constraint(
        'unique(product_tmpl_id, partner_id)',
        'You have already reviewed this product.',
    )


