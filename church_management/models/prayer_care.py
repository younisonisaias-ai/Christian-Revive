from odoo import models, fields, api

# Who may read a prayer request besides the person who sent it.
#   public       → shown on the Prayer Wall; all pastors
#   prayer_team  → not on the wall; all pastors / prayer team
#   pastor       → not on the wall; pastors only
#   private      → not on the wall; only the assigned pastor + senior pastor/admin
VISIBILITY = [
    ('public', 'Public – Prayer Wall'),
    ('prayer_team', 'Prayer Team'),
    ('pastor', 'Pastors Only'),
    ('private', 'Private – My Pastor Only'),
]

CARE_STATUS = [
    ('submitted', 'Submitted'),
    ('assigned', 'Assigned'),
    ('praying', 'Praying'),
    ('follow_up', 'Follow-Up'),
    ('answered', 'Answered'),
    ('closed', 'Closed'),
]

OPEN_STATUSES = ('submitted', 'assigned', 'praying', 'follow_up')

APP_FIELDS = [
    'id', 'name', 'subject', 'message', 'create_date', 'partner_id',
    'visibility', 'is_anonymous', 'category', 'urgency', 'care_status',
    'assigned_pastor_id', 'follow_up_date', 'testimony',
    'state', 'pray_count', 'prayed_by', 'response', 'response_by', 'response_date',
    'has_response_audio', 'response_audio_duration', 'response_audio_by', 'response_audio_date',
]

# Voice replies are capped so a stuck recording can't upload a huge file.
MAX_VOICE_BYTES = 8 * 1024 * 1024


class PrayerRequestCare(models.Model):
    """Church Management layer on top of the app's prayer requests: privacy
    levels, a care workflow, pastor assignment and follow-up."""
    _inherit = 'prayer.request'

    visibility = fields.Selection(VISIBILITY, string='Who Can See It', default='public', required=True)
    is_anonymous = fields.Boolean(
        string='Anonymous',
        help='Shown as "Anonymous" on the Prayer Wall. Pastors can still see who sent it.')
    requester_display_name = fields.Char(
        string='Requester (real name)', readonly=True,
        help='Kept when a request is sent anonymously.')
    category = fields.Selection([
        ('healing', 'Healing & Health'),
        ('family', 'Family'),
        ('spiritual', 'Spiritual Growth'),
        ('financial', 'Financial'),
        ('work', 'Work & Studies'),
        ('relationships', 'Relationships'),
        ('grief', 'Grief & Loss'),
        ('thanksgiving', 'Thanksgiving'),
        ('other', 'Other'),
    ], string='Category', default='other')
    urgency = fields.Selection([
        ('normal', 'Normal'), ('urgent', 'Urgent'),
    ], string='Urgency', default='normal', required=True)
    care_status = fields.Selection(
        CARE_STATUS, string='Care Status', default='submitted', required=True, index=True)
    assigned_pastor_id = fields.Many2one(
        'hr.employee', string='Assigned Pastor', domain=[('staff_role', '=', 'pastor')])
    follow_up_date = fields.Date(string='Follow-up Date')
    testimony = fields.Text(string='Answered / Testimony')

    # Pastor's spoken reply (recorded in the app); the member can listen to it.
    response_audio = fields.Binary(string='Voice Reply', attachment=True)
    response_audio_filename = fields.Char(string='Voice Reply Filename')
    response_audio_duration = fields.Integer(string='Voice Reply Length (s)')
    response_audio_by = fields.Char(string='Voice Reply By')
    response_audio_date = fields.Datetime(string='Voice Reply Date')
    has_response_audio = fields.Boolean(
        string='Has Voice Reply', compute='_compute_has_response_audio', store=True)

    @api.depends('response_audio')
    def _compute_has_response_audio(self):
        for rec in self:
            rec.has_response_audio = bool(rec.with_context(bin_size=True).response_audio)

    # ── Keep the Prayer Wall in step with the privacy choice ─────

    @api.model
    def _prepare_care_vals(self, vals):
        vals = dict(vals)
        if 'visibility' in vals:
            vals['is_published'] = vals['visibility'] == 'public'
        if vals.get('is_anonymous') and vals.get('name') and vals['name'] != 'Anonymous':
            vals['requester_display_name'] = vals['name']
            vals['name'] = 'Anonymous'
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for vals in vals_list:
            vals = self._prepare_care_vals(vals)
            # Route to the member's own pastor when there is one.
            if not vals.get('assigned_pastor_id') and vals.get('partner_id'):
                assignment = self.env['pastor.assignment'].sudo().search(
                    [('member_id', '=', vals['partner_id'])], limit=1)
                if assignment:
                    vals['assigned_pastor_id'] = assignment.pastor_id.id
                    vals.setdefault('care_status', 'assigned')
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        return super().write(self._prepare_care_vals(vals))

    def action_respond(self, response_text, responded_by=''):
        result = super().action_respond(response_text, responded_by)
        self.filtered(lambda r: r.care_status in ('submitted', 'assigned')).sudo().write(
            {'care_status': 'praying'})
        return result

    # ── Scope ────────────────────────────────────────────────────

    @api.model
    def _care_staff(self, requester_staff_id):
        """(employee, sees_everything, assigned_member_ids) for pastors/admins,
        or (None, False, []) for anyone else."""
        if not requester_staff_id:
            return None, False, []
        employee = self.env['hr.employee'].sudo().browse(int(requester_staff_id))
        if not employee.exists() or not employee.is_app_active:
            return None, False, []
        if employee.staff_role == 'admin' or (
                employee.staff_role == 'pastor' and employee.is_senior_pastor):
            return employee, True, []
        if employee.staff_role != 'pastor':
            return None, False, []
        members = self.env['pastor.assignment'].sudo().search(
            [('pastor_id', '=', employee.id)]).mapped('member_id').ids
        return employee, False, members

    @api.model
    def _care_domain(self, employee, sees_everything, member_ids):
        if sees_everything:
            return []
        return ['|', '|',
                ('assigned_pastor_id', '=', employee.id),
                ('partner_id', 'in', member_ids or [0]),
                ('visibility', 'in', ('public', 'prayer_team', 'pastor'))]

    # ── Flutter app RPC ─────────────────────────────────────────

    @api.model
    def app_get_care_prayers(self, requester_staff_id=None, status=None, query='', limit=200):
        """Prayer requests a pastor may see — including ones not on the wall.
        status: a care_status, 'open' (all unfinished) or empty for everything."""
        employee, sees_everything, members = self._care_staff(requester_staff_id)
        if not employee:
            return {'success': False, 'error': 'Not authorized'}
        domain = self._care_domain(employee, sees_everything, members)
        if status == 'open':
            domain.append(('care_status', 'in', OPEN_STATUSES))
        elif status:
            domain.append(('care_status', '=', status))
        if query:
            domain += ['|', '|', ('name', 'ilike', query), ('subject', 'ilike', query),
                       ('message', 'ilike', query)]
        records = self.sudo().search(domain, order='create_date desc', limit=limit)
        rows = records.read(APP_FIELDS + ['requester_display_name'])
        for row in rows:
            # Pastors see who really sent an anonymous request.
            if row.get('is_anonymous') and row.get('requester_display_name'):
                row['name'] = '%s (anonymous)' % row['requester_display_name']
            row.pop('requester_display_name', None)
        return {'success': True, 'prayers': rows}

    @api.model
    def app_update_care_prayer(self, prayer_id, vals, requester_staff_id=None):
        employee, sees_everything, members = self._care_staff(requester_staff_id)
        if not employee:
            return {'success': False, 'error': 'Not authorized'}
        domain = [('id', '=', int(prayer_id))] + self._care_domain(employee, sees_everything, members)
        prayer = self.sudo().search(domain, limit=1)
        if not prayer:
            return {'success': False, 'error': 'Prayer request not found'}

        vals = dict(vals or {})
        allowed = {'care_status', 'follow_up_date', 'testimony', 'urgency', 'category'}
        write_vals = {k: v for k, v in vals.items() if k in allowed}
        if vals.get('assign_to_me'):
            write_vals['assigned_pastor_id'] = employee.id
            if prayer.care_status == 'submitted' and 'care_status' not in write_vals:
                write_vals['care_status'] = 'assigned'
        if vals.get('remove_response_audio'):
            write_vals.update({
                'response_audio': False, 'response_audio_filename': False,
                'response_audio_duration': 0, 'response_audio_by': False,
                'response_audio_date': False,
            })
        audio = vals.get('response_audio')
        if audio:
            # base64 grows data by ~4/3; check the decoded size.
            if len(audio) * 3 // 4 > MAX_VOICE_BYTES:
                return {'success': False, 'error': 'Voice reply is too long. Please keep it under a few minutes.'}
            write_vals.update({
                'response_audio': audio,
                'response_audio_filename': 'voice_reply_%s.m4a' % prayer.id,
                'response_audio_duration': int(vals.get('response_audio_duration') or 0),
                'response_audio_by': employee.name,
                'response_audio_date': fields.Datetime.now(),
            })
        if write_vals:
            prayer.write(write_vals)

        text = (vals.get('response') or '').strip()
        if text:
            prayer.action_respond(text, employee.name)
        elif audio and not (prayer.response or '').strip():
            # Voice-only reply: leave a short note so older app versions and
            # the Prayer Wall still show that the pastor answered.
            prayer.action_respond('🎤 Voice reply from %s' % employee.name, employee.name)
        return {'success': True}

    @api.model
    def app_get_my_prayers(self, requester_partner_id):
        """A member's own prayer requests with their status and any response."""
        mode, scope = self.env['res.partner']._church_caller_scope(
            requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Not authorized'}
        records = self.sudo().search([('partner_id', '=', scope)], order='create_date desc', limit=100)
        return {'success': True, 'prayers': records.read([
            'id', 'subject', 'message', 'create_date', 'visibility', 'is_anonymous',
            'category', 'urgency', 'care_status', 'response', 'response_by',
            'response_date', 'pray_count', 'testimony',
            'has_response_audio', 'response_audio_duration', 'response_audio_by',
        ])}
