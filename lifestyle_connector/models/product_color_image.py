# -*- coding: utf-8 -*-
from odoo import fields, models


class LifestyleProductColorImage(models.Model):
    _name = 'lifestyle.product.color.image'
    _description = 'Revive Lifestyle Product Color Image'
    _order = 'sequence, id'
    _rec_name = 'color_name'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    color_name = fields.Char(
        string='Color / Finish',
        required=True,
        help='Example: Black, Blue, Walnut, Oak, Velvet Grey.',
    )
    image = fields.Image(
        string='App Image',
        max_width=1024,
        max_height=1024,
        required=True,
        help='Image shown in the Revive Lifestyle app when the customer selects this color.',
    )

    _unique_product_color = models.Constraint(
        'unique(product_tmpl_id, color_name)',
        'Each product can only have one app image per color/finish.',
    )
