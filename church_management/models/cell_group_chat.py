"""Cell group chat: the group's members, its leader and pastors message each
other in the app, with text and photos.

Who may read: the leader, the roster, admins and senior pastors, and an
associate pastor whose assigned members are in the group (the same rule as
the group page). Everyone who may read may post, except members the leader
has stopped from posting. The leader and pastors can delete any message;
authors can delete their own. New messages reach phones as push alerts,
which each person can mute per group.
"""
import base64
import binascii
import logging

from odoo import api, fields, models

from .pastor_alerts import _send_fcm

_logger = logging.getLogger(__name__)

MAX_TEXT = 2000
MAX_IMAGE_BYTES = 3 * 1024 * 1024
PAGE_SIZE = 40
# JPEG, PNG and WebP start with these bytes.
IMAGE_SIGNATURES = (b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n', b'RIFF')


def _image_bytes(data):
    """Decoded photo, or None when it is not an accepted picture."""
    if not data:
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(IMAGE_SIGNATURES):
        return None
    if raw.startswith(b'RIFF') and raw[8:12] != b'WEBP':
        return None
    return raw


class CellGroupMessage(models.Model):
    _name = 'cell.group.message'
    _description = 'Cell group chat message'
    _order = 'id desc'

    group_id = fields.Many2one('cell.group', required=True, ondelete='cascade', index=True)
    author_partner_id = fields.Many2one('res.partner', string='Member', ondelete='set null', index=True)
    author_employee_id = fields.Many2one('hr.employee', string='Staff', ondelete='set null')
    author_name = fields.Char(string='From', required=True)
    body = fields.Text(string='Message')
    image = fields.Binary(string='Photo', attachment=True)
    has_image = fields.Boolean(string='Photo attached', readonly=True)
    deleted = fields.Boolean(readonly=True)
    deleted_by = fields.Char(readonly=True)
    # Lets the app resend after a dropped connection without a duplicate.
    client_key = fields.Char(index=True, copy=False)

    def _for_app(self, who):
        self.ensure_one()
        mine = bool(
            (who['partner'] and self.author_partner_id == who['partner']) or
            (who['employee'] and self.author_employee_id == who['employee']))
        return {
            'id': self.id,
            'author_name': self.author_name,
            'author_partner_id': self.author_partner_id.id or False,
            'author_is_staff': bool(self.author_employee_id),
            'mine': mine,
            'body': '' if self.deleted else (self.body or ''),
            'has_image': self.has_image and not self.deleted,
            'deleted': self.deleted,
            'date': fields.Datetime.to_string(self.create_date),
        }


class CellGroupChatSeat(models.Model):
    """Per person and group: how far they have read and whether alerts are muted."""
    _name = 'cell.group.chat.seat'
    _description = 'Cell group chat reader'

    group_id = fields.Many2one('cell.group', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one('res.partner', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', ondelete='cascade', index=True)
    last_read_id = fields.Integer(default=0)
    muted = fields.Boolean()
    # Staff are alerted only in groups where they have taken part.
    has_posted = fields.Boolean()


class CellGroupChat(models.Model):
    _inherit = 'cell.group'

    chat_message_ids = fields.One2many('cell.group.message', 'group_id', string='Group chat')
    chat_silenced_ids = fields.Many2many(
        'res.partner', 'cell_group_chat_silenced_rel', 'group_id', 'partner_id',
        string='Cannot post in the chat',
        help='The leader or a pastor stopped these members from posting.')

    # ── Who is asking ───────────────────────────────────────────

    @api.model
    def _chat_caller(self, group_id, requester_partner_id=None, requester_staff_id=None):
        """(group, who) for an allowed caller, or (None, error)."""
        mode, scope = self.env['res.partner']._church_caller_scope(
            requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return None, 'Not authorized'
        group = self.sudo().browse(int(group_id or 0)).exists()
        if not group:
            return None, 'Group not found'
        partner = self.env['res.partner'].browse()
        employee = self.env['hr.employee'].browse()
        if mode == 'self':
            partner = self.env['res.partner'].sudo().browse(scope)
            if group.leader_id != partner and partner not in group.member_ids:
                return None, 'Only members of this group can open its chat'
            moderator = group.leader_id == partner
        else:
            if mode == 'assigned' and not (
                    group.leader_id.id in (scope or []) or set(group.member_ids.ids) & set(scope or [])):
                return None, 'Not authorized for this group'
            employee = self.env['hr.employee'].sudo().browse(int(requester_staff_id))
            moderator = True
        return group, {
            'partner': partner,
            'employee': employee,
            'name': (partner or employee).name or '',
            'moderator': moderator,
        }

    def _chat_seat(self, who):
        self.ensure_one()
        Seat = self.env['cell.group.chat.seat'].sudo()
        domain = [('group_id', '=', self.id)]
        domain += [('partner_id', '=', who['partner'].id)] if who['partner'] else \
            [('employee_id', '=', who['employee'].id)]
        seat = Seat.search(domain, limit=1)
        if not seat:
            seat = Seat.create({
                'group_id': self.id,
                'partner_id': who['partner'].id or False,
                'employee_id': who['employee'].id or False,
            })
        return seat

    def _chat_can_post(self, who):
        self.ensure_one()
        return not (who['partner'] and who['partner'] in self.chat_silenced_ids)

    def _chat_unread(self, who):
        self.ensure_one()
        Seat = self.env['cell.group.chat.seat'].sudo()
        domain = [('group_id', '=', self.id)]
        domain += [('partner_id', '=', who['partner'].id)] if who['partner'] else \
            [('employee_id', '=', who['employee'].id)]
        seat = Seat.search(domain, limit=1)
        if not seat and who['employee']:
            return 0  # pastors see counts only for groups they have opened
        # '!=' also keeps messages without that author (e.g. from staff).
        not_mine = [('author_partner_id', '!=', who['partner'].id)] if who['partner'] else \
            [('author_employee_id', '!=', who['employee'].id)]
        return self.env['cell.group.message'].sudo().search_count(
            [('group_id', '=', self.id), ('id', '>', seat.last_read_id), ('deleted', '=', False)]
            + not_mine)

    # ── App endpoints ───────────────────────────────────────────

    @api.model
    def app_chat_messages(self, group_id, after_id=0, before_id=0,
                          requester_partner_id=None, requester_staff_id=None):
        """Newest page of messages, older ones before [before_id], or new ones
        after [after_id] (for refreshing an open chat). Oldest first."""
        group, who = self._chat_caller(group_id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        Message = self.env['cell.group.message'].sudo()
        domain = [('group_id', '=', group.id)]
        if after_id:
            messages = Message.search(domain + [('id', '>', int(after_id))], order='id asc', limit=200)
            has_more = False
        else:
            if before_id:
                domain.append(('id', '<', int(before_id)))
            messages = Message.search(domain, order='id desc', limit=PAGE_SIZE + 1)
            has_more = len(messages) > PAGE_SIZE
            messages = messages[:PAGE_SIZE].sorted('id')
        seat = group._chat_seat(who)
        if not before_id and messages and messages[-1].id > seat.last_read_id:
            seat.last_read_id = messages[-1].id
        return {
            'success': True,
            'group': {'id': group.id, 'name': group.name, 'leader_id': group.leader_id.id or False},
            'messages': [m._for_app(who) for m in messages],
            'has_more': has_more,
            'can_post': group._chat_can_post(who),
            'can_moderate': who['moderator'],
            'muted': seat.muted,
            'silenced_ids': group.chat_silenced_ids.ids if who['moderator'] else [],
        }

    @api.model
    def app_chat_send(self, group_id, body='', image=None, client_key=None,
                      requester_partner_id=None, requester_staff_id=None):
        group, who = self._chat_caller(group_id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        if not group._chat_can_post(who):
            return {'success': False, 'error': 'The group leader has turned off posting for you.'}
        body = (body or '').strip()
        raw = _image_bytes(image) if image else None
        if image and raw is None:
            return {'success': False, 'error': 'That photo could not be sent. Use a JPG or PNG under 3 MB.'}
        if not body and raw is None:
            return {'success': False, 'error': 'Write a message or add a photo.'}
        if len(body) > MAX_TEXT:
            return {'success': False, 'error': 'Messages can be up to %d characters.' % MAX_TEXT}
        Message = self.env['cell.group.message'].sudo()
        author = [('author_partner_id', '=', who['partner'].id)] if who['partner'] else \
            [('author_employee_id', '=', who['employee'].id)]
        if client_key:
            earlier = Message.search(
                [('group_id', '=', group.id), ('client_key', '=', client_key)] + author, limit=1)
            if earlier:
                return {'success': True, 'message': earlier._for_app(who), 'replayed': True}
        message = Message.create({
            'group_id': group.id,
            'author_partner_id': who['partner'].id or False,
            'author_employee_id': who['employee'].id or False,
            'author_name': who['name'],
            'body': body,
            'image': base64.b64encode(raw) if raw is not None else False,
            'has_image': raw is not None,
            'client_key': client_key or False,
        })
        seat = group._chat_seat(who)
        seat.write({'last_read_id': message.id, 'has_posted': True})
        group._chat_notify(message, who)
        return {'success': True, 'message': message._for_app(who)}

    @api.model
    def app_chat_image(self, message_id, requester_partner_id=None, requester_staff_id=None):
        message = self.env['cell.group.message'].sudo().browse(int(message_id or 0)).exists()
        if not message:
            return {'success': False, 'error': 'Message not found'}
        group, who = self._chat_caller(message.group_id.id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        if message.deleted or not message.has_image:
            return {'success': False, 'error': 'This photo was removed'}
        image = message.image
        return {'success': True, 'image': image.decode() if isinstance(image, bytes) else image}

    @api.model
    def app_chat_delete(self, message_id, requester_partner_id=None, requester_staff_id=None):
        message = self.env['cell.group.message'].sudo().browse(int(message_id or 0)).exists()
        if not message:
            return {'success': False, 'error': 'Message not found'}
        group, who = self._chat_caller(message.group_id.id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        if not (who['moderator'] or message._for_app(who)['mine']):
            return {'success': False, 'error': 'You can delete only your own messages'}
        message.write({'deleted': True, 'body': False, 'image': False, 'deleted_by': who['name']})
        return {'success': True}

    @api.model
    def app_chat_set_muted(self, group_id, muted, requester_partner_id=None, requester_staff_id=None):
        group, who = self._chat_caller(group_id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        group._chat_seat(who).muted = bool(muted)
        return {'success': True, 'muted': bool(muted)}

    @api.model
    def app_chat_set_silenced(self, group_id, member_id, silenced,
                              requester_partner_id=None, requester_staff_id=None):
        """Leader or pastor: stop a member posting, or let them post again."""
        group, who = self._chat_caller(group_id, requester_partner_id, requester_staff_id)
        if not group:
            return {'success': False, 'error': who}
        if not who['moderator']:
            return {'success': False, 'error': 'Only the group leader or a pastor can do this'}
        member = self.env['res.partner'].sudo().browse(int(member_id or 0)).exists()
        if not member or member == group.leader_id:
            return {'success': False, 'error': 'The leader can always post'}
        group.write({'chat_silenced_ids': [(4 if silenced else 3, member.id)]})
        return {'success': True, 'silenced': bool(silenced)}

    @api.model
    def app_get_cell_groups(self, requester_partner_id=None, requester_staff_id=None):
        """Adds each group's unread chat count for the caller."""
        result = super().app_get_cell_groups(requester_partner_id, requester_staff_id)
        if not result.get('success'):
            return result
        partner = self.env['res.partner'].sudo().browse(
            int(requester_partner_id)) if requester_partner_id and not requester_staff_id else None
        employee = self.env['hr.employee'].sudo().browse(
            int(requester_staff_id)) if requester_staff_id else None
        who = {'partner': partner or self.env['res.partner'],
               'employee': employee or self.env['hr.employee']}
        for row in result['groups']:
            row['chat_unread'] = self.sudo().browse(row['id'])._chat_unread(who)
        return result

    # ── Alerts ──────────────────────────────────────────────────

    def _chat_notify(self, message, who):
        self.ensure_one()
        Seat = self.env['cell.group.chat.seat'].sudo()
        muted_partners = Seat.search([('group_id', '=', self.id), ('muted', '=', True),
                                      ('partner_id', '!=', False)]).mapped('partner_id')
        people = (self.leader_id | self.member_ids) - muted_partners - who['partner']
        tokens = set(people.filtered('app_fcm_token').mapped('app_fcm_token'))
        staff = Seat.search([('group_id', '=', self.id), ('employee_id', '!=', False),
                             ('has_posted', '=', True), ('muted', '=', False)]).mapped('employee_id')
        staff -= who['employee']
        tokens |= set(staff.filtered(lambda e: e.is_app_active and e.app_fcm_token).mapped('app_fcm_token'))
        tokens.discard(False)
        if not tokens:
            return
        text = (message.body or '').strip()
        preview = text if len(text) <= 120 else text[:117] + '...'
        body = '%s: %s' % (who['name'], preview) if preview else '%s sent a photo' % who['name']
        data = {'type': 'cell_chat', 'group_id': self.id, 'message_id': message.id}
        sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
        title = self.name
        tokens = list(tokens)
        # Send only once the message is really saved.
        self.env.cr.postcommit.add(lambda: _send_fcm(sa_path, tokens, title, body, data))
