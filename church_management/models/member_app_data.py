import json

from odoo import api, fields, models

# What the app keeps per member: music playlists & liked songs, hymn
# favourites, Bible highlights/bookmarks/notes. Stored as one JSON document
# per kind so a new phone can restore everything after logging in.
APP_DATA_KEYS = ('music', 'hymn_favorites', 'bible_annotations')
MAX_VALUE_BYTES = 2 * 1024 * 1024


class MemberAppData(models.Model):
    _name = 'church.member.app.data'
    _description = "Member's saved app data (playlists, favourites, Bible notes)"
    _order = 'partner_id, key'

    partner_id = fields.Many2one('res.partner', string='Member', required=True,
                                 ondelete='cascade', index=True)
    key = fields.Selection([
        ('music', 'Music playlists & liked songs'),
        ('hymn_favorites', 'Hymn favourites'),
        ('bible_annotations', 'Bible highlights, bookmarks & notes'),
    ], required=True)
    value = fields.Text(string='Data (JSON)')
    item_count = fields.Integer(string='Items', help='Rough count shown for reference.')
    updated_at = fields.Datetime(string='Last saved', readonly=True)

    _partner_key_uniq = models.Constraint(
        'unique(partner_id, key)',
        'Each member has one saved copy per kind of data.',
    )

    def _member(self, requester_partner_id):
        mode, scope = self.env['res.partner']._church_caller_scope(
            requester_partner_id=requester_partner_id)
        return scope if mode == 'self' else None

    @api.model
    def app_get_app_data(self, requester_partner_id=None):
        """Everything this member saved, with when each part was last saved."""
        partner_id = self._member(requester_partner_id)
        if not partner_id:
            return {'success': False, 'error': 'Please log in'}
        rows = self.sudo().search([('partner_id', '=', partner_id)])
        return {'success': True, 'data': {
            r.key: {
                'value': r.value or '',
                'updated_at': fields.Datetime.to_string(r.updated_at) if r.updated_at else '',
            } for r in rows
        }}

    @api.model
    def app_set_app_data(self, key, value, item_count=0, requester_partner_id=None):
        partner_id = self._member(requester_partner_id)
        if not partner_id:
            return {'success': False, 'error': 'Please log in'}
        if key not in APP_DATA_KEYS:
            return {'success': False, 'error': 'Unknown data'}
        value = value or ''
        if len(value.encode('utf-8')) > MAX_VALUE_BYTES:
            return {'success': False, 'error': 'Too much data to save'}
        try:
            json.loads(value or 'null')
        except ValueError:
            return {'success': False, 'error': 'Invalid data'}
        now = fields.Datetime.now()
        vals = {'value': value, 'updated_at': now, 'item_count': int(item_count or 0)}
        row = self.sudo().search([('partner_id', '=', partner_id), ('key', '=', key)], limit=1)
        if row:
            row.write(vals)
        else:
            self.sudo().create(dict(vals, partner_id=partner_id, key=key))
        return {'success': True, 'updated_at': fields.Datetime.to_string(now)}
