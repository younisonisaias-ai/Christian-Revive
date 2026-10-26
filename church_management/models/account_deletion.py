"""Delete my account (from the member app; required by the App Store).

The member re-enters their password. Their app login, sessions, devices,
saved app data (playlists, likes, Bible notes, hymn favourites), profile
photo and cell-group chat messages are removed. Church records the office
keeps — membership, family, attendance, giving — stay, with a note on the
contact. Someone with no church records is anonymised and archived.
"""
from werkzeug.security import check_password_hash

from odoo import api, fields, models

DELETED_NAME = 'Deleted app user'


class ResPartnerAccountDeletion(models.Model):
    _inherit = 'res.partner'

    def _has_church_records(self):
        """True when the church keeps records about this person."""
        self.ensure_one()
        if getattr(self, 'is_member', False) or self.family_id:
            return True
        env = self.env
        checks = [
            ('church.event.attendance', 'member_id'),
            ('church.service.rsvp', 'partner_id'),
            ('church.give.transaction', 'partner_id'),
            ('donation.transaction', 'partner_id'),
            ('church.give.pledge', 'member_id'),
        ]
        for model, field in checks:
            if model in env and field in env[model]._fields \
                    and env[model].sudo().search_count([(field, '=', self.id)], limit=1):
                return True
        return False

    @api.model
    def app_delete_account(self, password):
        """Deletes the signed-in member's app account after checking the password."""
        session = self.env['church.app.session']._current_member()
        partner = session.partner_id if session else self.browse()
        if not partner:
            return {'success': False, 'error': 'Please sign in again, then delete your account.'}
        partner = partner.sudo()
        if not password or not partner.app_password_hash \
                or not check_password_hash(partner.app_password_hash, password):
            return {'success': False, 'error': 'That password is not right.'}

        keep = partner._has_church_records()
        env = self.env
        # Saved app data and the member's own chat content.
        env['church.member.app.data'].sudo().search([('partner_id', '=', partner.id)]).unlink()
        if 'cell.group.message' in env:
            env['cell.group.message'].sudo().search([('author_partner_id', '=', partner.id)]).unlink()
            env['cell.group.message.reaction'].sudo().search([('partner_id', '=', partner.id)]).unlink()
            env['cell.group.chat.seat'].sudo().search([('partner_id', '=', partner.id)]).unlink()
        # Login, devices and every signed-in phone.
        vals = {
            'is_app_profile': False,
            'app_login_email': False,
            'app_password_hash': False,
            'app_fcm_token': False,
            'image_1920': False,
        }
        if not keep:
            vals.update({
                'name': DELETED_NAME, 'email': False, 'phone': False, 'street': False,
                'street2': False, 'city': False, 'zip': False, 'comment': False,
            })
            if 'mobile' in partner._fields:
                vals['mobile'] = False
        partner.write(vals)
        when = fields.Datetime.to_string(fields.Datetime.now())
        if keep and hasattr(partner, 'message_post'):
            partner.message_post(body=(
                'This member deleted their app account on %s (UTC). Their app login and app data '
                'were removed; church records were kept. Remove them from membership here if '
                'they asked for that.') % when)
        env['church.app.session'].sudo().search([('partner_id', '=', partner.id)]).unlink()
        if not keep:
            partner.active = False
        return {'success': True, 'kept_church_records': keep}
