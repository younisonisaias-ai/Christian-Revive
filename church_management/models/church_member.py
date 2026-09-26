from odoo import models, fields, api


class ChurchMember(models.Model):
    _inherit = 'res.partner'

    membership_status = fields.Selection([
        ('visitor', 'Visitor'),
        ('new_convert', 'New Convert'),
        ('member', 'Member'),
        ('worker', 'Worker'),
        ('leader', 'Leader'),
        ('inactive', 'Inactive'),
    ], string='Membership Status', default='visitor')

    leader_role = fields.Selection([
        ('elder', 'Elder'),
        ('pastor', 'Pastor'),
        ('evangelist', 'Evangelist'),
        ('deacon', 'Deacon'),
        ('deaconess', 'Deaconess'),
        ('teacher', 'Teacher'),
        ('preacher', 'Preacher'),
        ('minister', 'Minister'),
        ('worship_leader', 'Worship Leader'),
        ('music_director', 'Music Director'),
        ('youth_leader', 'Youth Leader'),
        ('small_group_leader', 'Small Group Leader'),
        ('treasurer', 'Treasurer'),
        ('church_secretary', 'Church Secretary'),
        ('church_administrator', 'Church Administrator'),
        ('church_clerk', 'Church Clerk'),
        ('care_taker', 'Care Taker'),
    ], string='Leader Role',
       help='Only meaningful when Membership Status is Leader.')

    # Pastoral care status — set by pastors, never by the member themself.
    care_status = fields.Selection([
        ('healthy', 'Doing Well'),
        ('new_member', 'New Member'),
        ('needs_follow_up', 'Needs Follow-Up'),
        ('prayer_needed', 'Prayer Needed'),
        ('hospitalized', 'Hospitalized'),
        ('bereavement', 'Bereavement'),
        ('counseling', 'Counseling'),
        ('at_risk', 'At Risk'),
        ('inactive', 'Inactive'),
    ], string='Care Status', default='healthy')
    care_status_date = fields.Date(string='Care Status Updated', readonly=True)

    member_join_date = fields.Date(string='Join Date')
    water_baptism_date = fields.Date(string='Water Baptism Date')
    holy_spirit_baptism_date = fields.Date(string='Holy Spirit Baptism Date')

    family_id = fields.Many2one('church.family', string='Family / Household')
    is_family_head = fields.Boolean(string='Family Head')
    guardian_id = fields.Many2one(
        'res.partner', string='Parent / Guardian',
        domain=[('is_member', '=', True)],
        help='Set for a dependent minor managed under a primary member account.',
    )

    # ── Church Management RPC (Phase 1) ─────────────────────────
    # The Flutter app authenticates to Odoo as a single shared service
    # account (see OdooService._authenticateOnce), not one Odoo user per
    # person — so role scoping cannot rely on Odoo's own res.groups/record
    # rules for these calls. Every method below takes the CALLER's identity
    # explicitly and enforces scope here in Python.

    def _church_caller_scope(self, requester_partner_id=None, requester_staff_id=None):
        """Resolve what the caller is allowed to see.

        Returns (mode, scope):
          mode='all'      → no restriction (church admin / senior pastor)
          mode='assigned' → scope is a list of member ids (associate pastor)
          mode='self'     → scope is the caller's own partner id (member)
          mode='denied'   → scope is None
        """
        if requester_staff_id:
            employee = self.env['hr.employee'].sudo().browse(requester_staff_id)
            if not employee.exists() or not employee.is_app_active:
                return ('denied', None)
            role = employee.staff_role
            if role == 'admin':
                return ('all', None)
            if role == 'pastor':
                if employee.is_senior_pastor:
                    return ('all', None)
                assigned = self.env['pastor.assignment'].sudo().search([
                    ('pastor_id', '=', employee.id),
                ]).mapped('member_id').ids
                return ('assigned', assigned)
            return ('denied', None)

        if requester_partner_id:
            partner = self.sudo().browse(requester_partner_id)
            if not partner.exists():
                return ('denied', None)
            return ('self', partner.id)

        return ('denied', None)

    @api.model
    def app_get_members(self, requester_partner_id=None, requester_staff_id=None, query=''):
        mode, scope = self._church_caller_scope(requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}

        domain = [('is_member', '=', True)]
        if mode == 'assigned':
            domain.append(('id', 'in', scope or [0]))
        elif mode == 'self':
            partner = self.sudo().browse(scope)
            family_ids = partner.family_id.member_ids.ids if partner.family_id else [partner.id]
            domain.append(('id', 'in', family_ids))
        # mode == 'all' → no extra restriction

        if query:
            domain.append(('name', 'ilike', query))

        members = self.sudo().search(domain, order='name')
        fields_to_read = [
            'id', 'name', 'email', 'phone', 'membership_status',
            'member_join_date', 'family_id', 'write_date',
        ]
        if mode != 'self':
            fields_to_read.append('care_status')
        return {'success': True, 'members': members.read(fields_to_read)}

    @api.model
    def app_get_member_detail(self, member_id, requester_partner_id=None, requester_staff_id=None):
        mode, scope = self._church_caller_scope(requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}

        member = self.sudo().browse(member_id)
        if not member.exists():
            return {'success': False, 'error': 'Member not found'}

        if mode == 'assigned' and member.id not in (scope or []):
            return {'success': False, 'error': 'Not authorized for this member'}
        if mode == 'self':
            partner = self.sudo().browse(scope)
            family_ids = partner.family_id.member_ids.ids if partner.family_id else [partner.id]
            if member.id not in family_ids:
                return {'success': False, 'error': 'Not authorized for this member'}

        data = member.read([
            'id', 'name', 'email', 'phone', 'date_of_birth', 'cnic',
            'membership_status', 'leader_role', 'member_join_date',
            'water_baptism_date', 'holy_spirit_baptism_date',
            'family_id', 'is_family_head', 'guardian_id',
            'membership_type', 'contribution_preference', 'write_date',
        ] + ([] if mode == 'self' else ['care_status', 'care_status_date']))[0]
        return {'success': True, 'member': data}

    @api.model
    def app_create_member(self, vals, requester_staff_id=None):
        mode, _scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized to create members'}
        vals = dict(vals or {})
        vals['is_member'] = True
        member = self.sudo().create(vals)
        return {'success': True, 'member_id': member.id}

    @api.model
    def app_update_member(self, member_id, vals, requester_partner_id=None, requester_staff_id=None):
        mode, scope = self._church_caller_scope(requester_partner_id, requester_staff_id)
        if mode == 'denied':
            return {'success': False, 'error': 'Not authorized'}

        member = self.sudo().browse(member_id)
        if not member.exists():
            return {'success': False, 'error': 'Member not found'}

        vals = dict(vals or {})
        if mode == 'self':
            if member.id != scope:
                return {'success': False, 'error': 'Not authorized for this member'}
            # Members may edit their own contact details only — never their
            # own membership lifecycle fields (status, baptism, family).
            allowed = {'email', 'phone', 'street', 'city'}
            vals = {k: v for k, v in vals.items() if k in allowed}
        elif mode == 'assigned' and member.id not in (scope or []):
            return {'success': False, 'error': 'Not authorized for this member'}

        if 'care_status' in vals:
            vals['care_status_date'] = fields.Date.context_today(self)
        member.sudo().write(vals)
        return {'success': True}

    @api.model
    def app_get_my_family(self, requester_partner_id):
        mode, scope = self._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Not authorized'}
        partner = self.sudo().browse(scope)
        if not partner.family_id:
            return {'success': True, 'family': None, 'members': []}
        members = partner.family_id.member_ids.read([
            'id', 'name', 'membership_status', 'guardian_id',
        ])
        return {
            'success': True,
            'family': {'id': partner.family_id.id, 'name': partner.family_id.name},
            'members': members,
        }
