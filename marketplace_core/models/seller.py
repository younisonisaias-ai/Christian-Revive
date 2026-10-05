# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

PHONE_RE = re.compile(r'^[0-9+\-\s()]+$')


def _validate_phone_number(value):
    """Returns an error message string if value isn't a plausible phone
    number (digits only, plus optional +/-/space/parens formatting), or
    None if it's fine to save. Empty/unset values are always fine -
    required-ness is a separate check where it matters."""
    value = (value or '').strip()
    if not value:
        return None
    if not PHONE_RE.match(value):
        return _('may only contain numbers.')
    if len(re.sub(r'\D', '', value)) < 7:
        return _('must be a valid phone number.')
    return None


class MarketplaceSeller(models.Model):
    _name = 'marketplace.seller'
    _description = 'Marketplace Seller Shop'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(string='Shop Name', required=True, tracking=True)
    slug = fields.Char(
        string='Shop URL Slug', required=True, copy=False, index=True,
        help='Used in the public shop URL: /market/shop/<slug>')
    partner_id = fields.Many2one(
        'res.partner', string='Owner', required=True, ondelete='restrict',
        index=True)
    user_id = fields.Many2one(
        'res.users', string='Owner User', compute='_compute_user_id',
        store=True)
    logo = fields.Image(string='Shop Logo', max_width=512, max_height=512)
    banner = fields.Image(string='Shop Banner', max_width=1920, max_height=1080)
    bio = fields.Text(string='Shop Bio')
    story = fields.Html(string='Shop Story', sanitize=True)
    instagram_handle = fields.Char(string='Instagram Handle')
    whatsapp_number = fields.Char(string='WhatsApp Number')
    city = fields.Char()
    country_id = fields.Many2one('res.country', string='Country')
    business_type = fields.Selection([
        ('individual', 'Individual Seller'),
        ('home_based', 'Home-Based Business'),
        ('boutique', 'Boutique / Retail Store'),
        ('online_shop', 'Online Shop (Instagram/Facebook/Website)'),
        ('other', 'Other'),
    ], string='Business Type', tracking=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('suspended', 'Suspended'),
    ], default='draft', required=True, tracking=True, index=True)
    is_featured = fields.Boolean(string='Featured Shop', tracking=True)
    zero_fee_forever = fields.Boolean(
        string='Zero Fees Forever',
        help='Early-seller incentive: this shop never pays platform commission.')
    commission_pct = fields.Float(
        string='Commission (%)', default=0.0, tracking=True,
        help='Platform commission on this seller\'s sales. Marketplace '
             'strategy is zero seller fees; keep 0 unless deliberately changed.')

    # ------------------------------------------------------------------
    # KYC
    # ------------------------------------------------------------------
    kyc_status = fields.Selection([
        ('none', 'Not Submitted'),
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ], default='none', required=True, tracking=True,
        help='Light KYC: required before first payout, not before first listing.')
    kyc_id_type = fields.Selection([
        ('cnic', 'CNIC (Pakistan)'),
        ('passport', 'Passport'),
        ('driving_license', 'Driving License'),
        ('other', 'Other'),
    ], string='ID Type')
    kyc_id_number = fields.Char(string='ID Number')
    kyc_document_ids = fields.Many2many(
        'ir.attachment', 'marketplace_seller_kyc_attachment_rel',
        'seller_id', 'attachment_id', string='KYC Documents')
    kyc_notes = fields.Text(string='KYC Review Notes')

    # ------------------------------------------------------------------
    # Payout details
    # ------------------------------------------------------------------
    payout_method = fields.Selection([
        ('bank', 'Bank Transfer'),
        ('jazzcash', 'JazzCash'),
        ('easypaisa', 'EasyPaisa'),
    ], string='Payout Method', default='bank')
    bank_name = fields.Char()
    bank_account_title = fields.Char(string='Account Title')
    bank_account_number = fields.Char(string='Account Number / IBAN')
    mobile_wallet_number = fields.Char(
        string='Mobile Wallet Number',
        help='JazzCash / EasyPaisa registered mobile number.')

    # ------------------------------------------------------------------
    # Social graph
    # ------------------------------------------------------------------
    follower_ids = fields.Many2many(
        'res.partner', 'marketplace_seller_follower_rel',
        'seller_id', 'partner_id', string='Followers')
    follower_count = fields.Integer(compute='_compute_follower_count')

    # ------------------------------------------------------------------
    # Relations & stats
    # ------------------------------------------------------------------
    listing_ids = fields.One2many(
        'product.template', 'marketplace_seller_id', string='Listings')
    listing_count = fields.Integer(compute='_compute_listing_stats')
    active_listing_count = fields.Integer(compute='_compute_listing_stats')
    sold_listing_count = fields.Integer(compute='_compute_listing_stats')

    order_ids = fields.One2many(
        'sale.order', 'marketplace_seller_id', string='Orders')
    order_count = fields.Integer(compute='_compute_order_stats')
    total_sales = fields.Monetary(
        compute='_compute_order_stats', string='Total Sales')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        required=True)

    review_ids = fields.One2many('marketplace.review', 'seller_id')
    review_count = fields.Integer(compute='_compute_rating')
    rating_avg = fields.Float(compute='_compute_rating', digits=(3, 2))

    wallet_transaction_ids = fields.One2many(
        'marketplace.wallet.transaction', 'seller_id')
    wallet_balance = fields.Monetary(compute='_compute_wallet_balance')
    payout_ids = fields.One2many('marketplace.seller.payout', 'seller_id')

    _slug_uniq = models.Constraint(
        'unique(slug)',
        'This shop URL is already taken.',
    )
    _partner_uniq = models.Constraint(
        'unique(partner_id)',
        'This user already has a marketplace shop.',
    )

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('partner_id')
    def _compute_user_id(self):
        for seller in self:
            seller.user_id = seller.partner_id.user_ids[:1]

    def _compute_follower_count(self):
        for seller in self:
            seller.follower_count = len(seller.follower_ids)

    def _compute_listing_stats(self):
        for seller in self:
            listings = seller.listing_ids
            seller.listing_count = len(listings)
            seller.active_listing_count = len(listings.filtered(
                lambda l: l.listing_state == 'active'))
            seller.sold_listing_count = len(listings.filtered(
                lambda l: l.listing_state == 'sold'))

    def _compute_order_stats(self):
        for seller in self:
            orders = seller.order_ids.filtered(
                lambda o: o.state == 'sale')
            seller.order_count = len(orders)
            seller.total_sales = sum(orders.mapped('marketplace_item_total'))

    def _compute_rating(self):
        for seller in self:
            reviews = seller.review_ids.filtered(
                lambda r: r.state == 'published')
            seller.review_count = len(reviews)
            seller.rating_avg = (
                sum(int(r.rating) for r in reviews) / len(reviews)
                if reviews else 0.0)

    def _compute_wallet_balance(self):
        for seller in self:
            seller.wallet_balance = sum(
                seller.wallet_transaction_ids
                .filtered(lambda t: t.state == 'done')
                .mapped('signed_amount'))

    @api.constrains('slug')
    def _check_slug(self):
        for seller in self:
            if not re.match(r'^[a-z0-9]+(?:-[a-z0-9]+)*$', seller.slug or ''):
                raise ValidationError(_(
                    'The shop URL may only contain lowercase letters, '
                    'numbers and hyphens.'))

    @api.constrains('commission_pct')
    def _check_commission(self):
        for seller in self:
            if not 0 <= seller.commission_pct <= 100:
                raise ValidationError(_('Commission must be between 0 and 100%.'))

    @api.constrains('whatsapp_number', 'mobile_wallet_number')
    def _check_phone_fields(self):
        labels = {
            'whatsapp_number': _('WhatsApp number'),
            'mobile_wallet_number': _('Mobile wallet number'),
        }
        for seller in self:
            for field_name, label in labels.items():
                error = _validate_phone_number(seller[field_name])
                if error:
                    raise ValidationError('%s: %s' % (label, error))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _slugify(self, name):
        slug = re.sub(r'[^a-z0-9]+', '-', (name or '').lower()).strip('-')
        if not slug:
            slug = 'shop'
        base, i = slug, 1
        while self.sudo().search_count([('slug', '=', slug)]):
            i += 1
            slug = '%s-%s' % (base, i)
        return slug

    def _effective_commission_pct(self):
        self.ensure_one()
        if self.zero_fee_forever:
            return 0.0
        return self.commission_pct

    def is_followed_by(self, partner):
        self.ensure_one()
        return bool(partner) and partner.id in self.follower_ids.ids

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_submit(self):
        self.filtered(lambda s: s.state == 'draft').write({'state': 'pending'})

    def action_approve(self):
        self.write({'state': 'approved'})
        for seller in self:
            seller.message_post(body=_('Shop approved and live on the marketplace.'))

    def action_suspend(self):
        self.write({'state': 'suspended'})
        self.listing_ids.filtered(
            lambda l: l.listing_state == 'active').write({
                'listing_state': 'removed', 'is_published': False,
                'removed_by_suspension': True})

    def action_reactivate(self):
        self.write({'state': 'approved'})
        self.listing_ids.filtered(
            lambda l: l.removed_by_suspension).write({
                'listing_state': 'active', 'is_published': True,
                'removed_by_suspension': False})

    def action_submit_kyc(self):
        for seller in self:
            if not seller.kyc_id_number or not seller.kyc_document_ids:
                raise UserError(_(
                    'Please provide an ID number and upload at least one '
                    'identity document before submitting KYC.'))
        self.write({'kyc_status': 'pending'})

    def action_verify_kyc(self):
        self.write({'kyc_status': 'verified'})
        for seller in self:
            seller.message_post(body=_('KYC verified. Payouts are now enabled.'))

    def action_reject_kyc(self):
        self.write({'kyc_status': 'rejected'})

    def action_view_listings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Listings'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('marketplace_seller_id', '=', self.id)],
            'context': {
                'default_marketplace_seller_id': self.id,
                'default_is_marketplace_listing': True,
            },
        }

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Orders'),
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': [('marketplace_seller_id', '=', self.id)],
        }

    def action_view_reviews(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reviews'),
            'res_model': 'marketplace.review',
            'view_mode': 'list,form',
            'domain': [('seller_id', '=', self.id)],
        }

    def action_toggle_follow(self, partner):
        """Follow/unfollow the shop for the given partner. Returns new state."""
        self.ensure_one()
        if partner.id in self.follower_ids.ids:
            self.sudo().write({'follower_ids': [(3, partner.id)]})
            return False
        self.sudo().write({'follower_ids': [(4, partner.id)]})
        return True

    # ------------------------------------------------------------------
    # Sales analytics
    # ------------------------------------------------------------------
    def get_sales_analytics(self, weeks=8):
        """Weekly sales totals/counts for the last N weeks, plus a few
        top-line numbers a seller actually cares about: average order
        value, sell-through rate, and best-selling listing."""
        self.ensure_one()
        orders = self.order_ids.filtered(lambda o: o.state == 'sale')

        from datetime import timedelta
        today = fields.Date.today()
        # Week buckets ending today, oldest first.
        buckets = []
        for w in range(weeks - 1, -1, -1):
            end = today - timedelta(days=7 * w)
            start = end - timedelta(days=6)
            week_orders = orders.filtered(
                lambda o, s=start, e=end:
                    o.create_date and s <= o.create_date.date() <= e)
            buckets.append({
                'label': start.strftime('%d %b'),
                'total': sum(week_orders.mapped('marketplace_item_total')),
                'count': len(week_orders),
            })

        total_listings = len(self.listing_ids)
        sold_listings = len(self.listing_ids.filtered(
            lambda l: l.listing_state == 'sold'))
        sell_through = (sold_listings / total_listings * 100.0
                        if total_listings else 0.0)
        avg_order_value = (
            sum(orders.mapped('marketplace_item_total')) / len(orders)
            if orders else 0.0)

        top_listing = False
        if orders:
            counts = {}
            for order in orders:
                for listing in order._get_marketplace_listings():
                    counts[listing] = counts.get(listing, 0) + 1
            if counts:
                top_listing = max(counts, key=counts.get)

        return {
            'weekly': buckets,
            'avg_order_value': avg_order_value,
            'sell_through_pct': sell_through,
            'total_revenue': sum(orders.mapped('marketplace_item_total')),
            'top_listing': top_listing,
        }
