# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MarketplaceBrand(models.Model):
    _name = 'marketplace.brand'
    _description = 'Marketplace Brand'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    logo = fields.Image(max_width=256, max_height=256)
    is_luxury = fields.Boolean(
        string='Luxury / Verification Eligible',
        help='Items of this brand can be sent for item verification.')
    active = fields.Boolean(default=True)
    listing_count = fields.Integer(compute='_compute_listing_count')

    _name_uniq = models.Constraint(
        'unique(name)',
        'This brand already exists.',
    )

    def _compute_listing_count(self):
        counts = dict(self.env['product.template']._read_group(
            [('marketplace_brand_id', 'in', self.ids)],
            ['marketplace_brand_id'], ['__count']))
        for brand in self:
            brand.listing_count = counts.get(brand, 0)

    @api.model
    def get_or_create_by_name(self, name):
        """Sellers can type a brand that isn't in the catalog yet — it is
        added on the fly so the catalog grows from real listings instead
        of blocking the seller on a fixed admin-curated list."""
        name = (name or '').strip()
        if not name:
            return self.browse()
        brands = self.sudo()
        existing = brands.search([('name', '=ilike', name)], limit=1)
        return existing or brands.create({'name': name})


class MarketplaceSize(models.Model):
    _name = 'marketplace.size'
    _description = 'Marketplace Size'
    _order = 'category, sequence, name'

    name = fields.Char(required=True)
    category = fields.Selection([
        ('women', 'Women'),
        ('men', 'Men'),
        ('kids', 'Kids'),
        ('shoes', 'Shoes'),
        ('other', 'Other'),
    ], required=True, default='women')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _name_category_uniq = models.Constraint(
        'unique(name, category)',
        'This size already exists in this category.',
    )

    @api.model
    def get_or_create(self, name, category=None):
        """Same escape hatch as brands: not every item fits the preset
        size list (custom tailoring, imported sizing, non-clothing goods),
        so a typed value is accepted and added to the catalog."""
        name = (name or '').strip()
        if not name:
            return self.browse()
        valid_categories = dict(self._fields['category'].selection)
        category = category if category in valid_categories else 'other'
        sizes = self.sudo()
        existing = sizes.search(
            [('name', '=ilike', name), ('category', '=', category)], limit=1)
        return existing or sizes.create({'name': name, 'category': category})


class MarketplaceBannedKeyword(models.Model):
    _name = 'marketplace.banned.keyword'
    _description = 'Banned Item Keyword'
    _order = 'name'

    name = fields.Char(required=True, index=True)
    reason = fields.Char(help='Why items matching this keyword are banned.')
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        'unique(name)',
        'This keyword is already listed.',
    )

    @api.model
    def _find_match(self, *texts):
        """Return the first banned keyword found in any of the given texts."""
        haystack = ' '.join(t.lower() for t in texts if t)
        if not haystack:
            return False
        for kw in self.search([]):
            if kw.name.lower() in haystack:
                return kw
        return False
