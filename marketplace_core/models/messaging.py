# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MarketplaceThread(models.Model):
    _name = 'marketplace.thread'
    _description = 'Buyer-Seller Conversation'
    _order = 'last_message_date desc, id desc'
    _rec_name = 'display_subject'

    buyer_partner_id = fields.Many2one(
        'res.partner', string='Buyer', required=True, index=True,
        ondelete='cascade')
    seller_id = fields.Many2one(
        'marketplace.seller', required=True, index=True, ondelete='cascade')
    listing_id = fields.Many2one(
        'product.template', string='About Listing', ondelete='set null')
    message_ids = fields.One2many(
        'marketplace.thread.message', 'thread_id', string='Messages')
    last_message_date = fields.Datetime(index=True)
    display_subject = fields.Char(compute='_compute_display_subject')

    _buyer_seller_listing_uniq = models.Constraint(
        'unique(buyer_partner_id, seller_id, listing_id)',
        'A conversation for this listing already exists.',
    )

    @api.depends('buyer_partner_id', 'seller_id', 'listing_id')
    def _compute_display_subject(self):
        for thread in self:
            if thread.listing_id:
                thread.display_subject = '%s · %s' % (
                    thread.listing_id.name, thread.seller_id.name)
            else:
                thread.display_subject = '%s · %s' % (
                    thread.buyer_partner_id.name, thread.seller_id.name)

    @api.model
    def get_or_create_thread(self, buyer_partner, seller, listing=None):
        if seller.partner_id == buyer_partner:
            raise UserError(_('You cannot message your own shop.'))
        domain = [
            ('buyer_partner_id', '=', buyer_partner.id),
            ('seller_id', '=', seller.id),
            ('listing_id', '=', listing.id if listing else False),
        ]
        thread = self.sudo().search(domain, limit=1)
        if not thread:
            thread = self.sudo().create({
                'buyer_partner_id': buyer_partner.id,
                'seller_id': seller.id,
                'listing_id': listing.id if listing else False,
                'last_message_date': fields.Datetime.now(),
            })
        return thread

    def post_message(self, author_partner, body, image=None, image_filename=None,
                     video=None, video_filename=None):
        self.ensure_one()
        body = (body or '').strip()
        if not body:
            raise UserError(_('Message cannot be empty.'))
        allowed = (self.buyer_partner_id | self.seller_id.partner_id)
        if author_partner not in allowed:
            raise UserError(_('You are not part of this conversation.'))
        vals = {
            'thread_id': self.id,
            'author_partner_id': author_partner.id,
            'body': body,
        }
        if image:
            vals['image'] = image
            vals['image_filename'] = image_filename or 'photo.jpg'
        if video:
            vals['video'] = video
            vals['video_filename'] = video_filename or 'video.mp4'
        message = self.env['marketplace.thread.message'].sudo().create(vals)
        self.sudo().last_message_date = fields.Datetime.now()
        return message

    def partner_can_access(self, partner):
        self.ensure_one()
        return partner in (self.buyer_partner_id | self.seller_id.partner_id)

    def mark_read(self, partner):
        self.ensure_one()
        self.message_ids.sudo().filtered(
            lambda m: not m.is_read and m.author_partner_id != partner
        ).write({'is_read': True})

    def unread_count(self, partner):
        self.ensure_one()
        return len(self.message_ids.filtered(
            lambda m: not m.is_read and m.author_partner_id != partner))


class MarketplaceThreadMessage(models.Model):
    _name = 'marketplace.thread.message'
    _description = 'Conversation Message'
    _order = 'create_date asc, id asc'

    thread_id = fields.Many2one(
        'marketplace.thread', required=True, ondelete='cascade', index=True)
    author_partner_id = fields.Many2one(
        'res.partner', string='Author', required=True)
    body = fields.Text(required=True)
    image = fields.Binary(attachment=True)
    image_filename = fields.Char()
    video = fields.Binary(attachment=True)
    video_filename = fields.Char()
    is_read = fields.Boolean(default=False)

    @api.constrains('video', 'video_filename')
    def _check_video(self):
        max_bytes = 50 * 1024 * 1024  # 50MB
        allowed_ext = ('.mp4', '.mov', '.webm', '.avi', '.mkv', '.m4v')
        for msg in self:
            if not msg.video:
                continue
            approx_bytes = len(msg.video) * 3 / 4
            if approx_bytes > max_bytes:
                raise ValidationError(_(
                    'Video must be smaller than 50MB.'))
            name = (msg.video_filename or '').lower()
            if name and not name.endswith(allowed_ext):
                raise ValidationError(_(
                    'Video must be a common video format '
                    '(MP4, MOV, WebM, AVI, MKV).'))
