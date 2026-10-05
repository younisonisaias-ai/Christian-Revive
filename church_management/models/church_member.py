from odoo import models, fields, api

# Profile fields a member may edit about themself from the app. Lifecycle
# fields (status, baptism, transfer, member number) stay staff-only.
MEMBER_SELF_EDITABLE = {
    'email', 'phone', 'street', 'city', 'date_of_birth', 'gender', 'marital_status',
    'wedding_anniversary', 'occupation', 'talents', 'spiritual_gifts',
    'ministry_interests', 'emergency_contact_name', 'emergency_contact_phone',
}

# Fields that make up "profile completeness": (field, label shown to the member)
PROFILE_CHECKLIST = [
    ('image_1920', 'Profile photo'),
    ('phone', 'Phone number'),
    ('email', 'Email'),
    ('date_of_birth', 'Date of birth'),
    ('gender', 'Gender'),
    ('marital_status', 'Marital status'),
    ('city', 'City'),
    ('occupation', 'Profession'),
    ('emergency_contact_name', 'Emergency contact'),
    ('emergency_contact_phone', 'Emergency contact phone'),
]

FAMILY_RELATIONSHIPS = [
    ('spouse', 'Husband / Wife'),
    ('son', 'Son'),
    ('daughter', 'Daughter'),
    ('father', 'Father'),
    ('mother', 'Mother'),
    ('brother', 'Brother'),
    ('sister', 'Sister'),
    ('grandparent', 'Grandparent'),
    ('grandchild', 'Grandchild'),
    ('other', 'Other relative'),
]

# What a member may set on a relative they add themselves.
FAMILY_SELF_FIELDS = {'name', 'phone', 'gender', 'date_of_birth', 'family_relationship'}

MEMBER_PROFILE_FIELDS = [
    'member_number', 'gender', 'marital_status', 'wedding_anniversary', 'occupation',
    'talents', 'spiritual_gifts', 'ministry_interests', 'emergency_contact_name',
    'emergency_contact_phone', 'baptism_place', 'previous_church', 'transfer_in_date',
    'transfer_out_date', 'transfer_to_church', 'street', 'city',
]


class ChurchMember(models.Model):
    _inherit = 'res.partner'

    membership_status = fields.Selection([
        ('visitor', 'Visitor'),
        ('new_convert', 'New Convert'),
        ('member', 'Member'),
        ('worker', 'Worker'),
        ('leader', 'Leader'),
        ('inactive', 'Inactive'),
        ('transferred', 'Transferred Out'),
        ('deceased', 'Deceased'),
    ], string='Membership Status', default='visitor')

    # ── Member profile ──────────────────────────────────────────
    member_number = fields.Char(
        string='Member No.', readonly=True, copy=False, index=True,
        help='Assigned automatically when someone becomes a member.')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string='Gender')
    marital_status = fields.Selection([
        ('single', 'Single'), ('married', 'Married'), ('widowed', 'Widowed'),
        ('divorced', 'Divorced'), ('separated', 'Separated'),
    ], string='Marital Status')
    wedding_anniversary = fields.Date(string='Wedding Anniversary')
    occupation = fields.Char(string='Profession / Occupation')
    talents = fields.Char(string='Skills & Talents')
    spiritual_gifts = fields.Char(string='Spiritual Gifts')
    ministry_interests = fields.Char(string='Ministry Interests')
    emergency_contact_name = fields.Char(string='Emergency Contact')
    emergency_contact_phone = fields.Char(string='Emergency Contact Phone')
    baptism_place = fields.Char(string='Place of Baptism')
    previous_church = fields.Char(string='Previous Church')
    transfer_in_date = fields.Date(string='Transferred In On')
    transfer_out_date = fields.Date(string='Transferred Out On')
    transfer_to_church = fields.Char(string='Transferred To')
    profile_completeness = fields.Integer(
        string='Profile Complete (%)', compute='_compute_profile_completeness')

    def _profile_missing(self):
        self.ensure_one()
        return [label for field, label in PROFILE_CHECKLIST if not self[field]]

    def _compute_profile_completeness(self):
        total = len(PROFILE_CHECKLIST)
        for partner in self:
            missing = len(partner._profile_missing()) if partner.id else total
            partner.profile_completeness = round((total - missing) * 100 / total)

    # ── Member numbers ──────────────────────────────────────────

    def _assign_member_numbers(self):
        Sequence = self.env['ir.sequence'].sudo()
        # Relatives added by a member get a number only once the church verifies them.
        for partner in self.filtered(
                lambda p: p.is_member and not p.member_number and p.family_verified):
            partner.sudo().with_context(allow_member_number=True).write(
                {'member_number': Sequence.next_by_code('church.member.number')})

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._assign_member_numbers()
        return partners

    def write(self, vals):
        # Member numbers are issued by the sequence only, never typed in.
        if 'member_number' in vals and not self.env.context.get('allow_member_number'):
            vals = {k: v for k, v in vals.items() if k != 'member_number'}
        result = super().write(vals)
        if vals.get('is_member') or vals.get('family_verified'):
            self._assign_member_numbers()
        return result

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
    family_relationship = fields.Selection(
        FAMILY_RELATIONSHIPS, string='Relationship',
        help='How this person is related to the family head / the member who added them.')
    family_verified = fields.Boolean(
        string='Verified by Church', default=True,
        help='Unticked for relatives a member added in the app. Tick once the '
             'church has confirmed them — they then get a member number.')
    added_by_partner_id = fields.Many2one(
        'res.partner', string='Added by Member', readonly=True,
        help='The member who added this relative from the app.')
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
            'member_join_date', 'family_id', 'write_date', 'member_number',
            'family_relationship', 'family_verified', 'added_by_partner_id',
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
            'family_relationship', 'family_verified', 'added_by_partner_id',
        ] + MEMBER_PROFILE_FIELDS
          + ([] if mode == 'self' else ['care_status', 'care_status_date']))[0]
        data['profile_completeness'] = member.profile_completeness
        data['profile_missing'] = member._profile_missing()
        data['can_edit_profile'] = mode != 'self' or member.id == scope
        # A member may edit/remove only relatives they added themselves.
        data['can_edit_relative'] = mode == 'self' and member.added_by_partner_id.id == scope
        data['can_verify'] = mode in ('all', 'assigned') and not member.family_verified
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
            # Members may edit their own personal details only — never their
            # own membership lifecycle fields (status, baptism, family, transfer).
            vals = {k: v for k, v in vals.items() if k in MEMBER_SELF_EDITABLE}
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

    # ── Members adding their own relatives ──────────────────────

    def _clean_relative_vals(self, vals):
        vals = {k: v for k, v in dict(vals or {}).items() if k in FAMILY_SELF_FIELDS}
        if 'name' in vals:
            vals['name'] = (vals['name'] or '').strip()
        valid = dict(FAMILY_RELATIONSHIPS)
        if vals.get('family_relationship') not in valid:
            vals.pop('family_relationship', None)
        for key in ('phone', 'gender', 'date_of_birth'):
            if key in vals and not vals[key]:
                vals[key] = False
        return vals

    def _is_minor(self, birth_date):
        if not birth_date:
            return False
        dob = fields.Date.to_date(birth_date)
        today = fields.Date.context_today(self)
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        return age < 18

    @api.model
    def app_add_my_family_member(self, vals, requester_partner_id=None):
        """A logged-in member adds a relative to their household.

        The relative shows in the family straight away but stays a Visitor,
        unverified and without a member number until the church confirms them.
        """
        mode, scope = self._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Please log in as a member'}
        me = self.sudo().browse(scope)
        vals = self._clean_relative_vals(vals)
        if not vals.get('name'):
            return {'success': False, 'error': 'Please enter a name'}

        family = me.family_id
        if not family:
            surname = (me.name or '').strip().split()[-1] if (me.name or '').strip() else ''
            family = self.env['church.family'].sudo().create({
                'name': f'{surname} Family'.strip() if surname else 'My Family',
                'head_id': me.id,
            })
            me.sudo().write({'family_id': family.id, 'is_family_head': True})

        vals.update({
            'family_id': family.id,
            'is_member': True,
            'membership_status': 'visitor',
            'family_verified': False,
            'added_by_partner_id': me.id,
        })
        if self._is_minor(vals.get('date_of_birth')):
            vals['guardian_id'] = me.id
        relative = self.sudo().create(vals)

        # Pastors who care for this member also see the relative.
        Assignment = self.env['pastor.assignment'].sudo()
        for pastor in Assignment.search([('member_id', '=', me.id)]).mapped('pastor_id'):
            Assignment.create({'pastor_id': pastor.id, 'member_id': relative.id,
                               'notes': f'Relative added by {me.name}'})
        rel_label = dict(FAMILY_RELATIONSHIPS).get(relative.family_relationship, 'relative')
        self.env['church.alerts'].notify_pastors(
            me, '👪 New family member to verify',
            f'{me.name} added {relative.name} ({rel_label})', 'relative', relative.id)
        return {'success': True, 'member_id': relative.id, 'family_id': family.id}

    def _my_relative(self, member_id, requester_partner_id):
        mode, scope = self._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return None, 'Please log in as a member'
        relative = self.sudo().browse(member_id)
        if not relative.exists() or relative.added_by_partner_id.id != scope:
            return None, 'You can only change relatives you added'
        return relative, None

    @api.model
    def app_update_my_family_member(self, member_id, vals, requester_partner_id=None):
        relative, error = self._my_relative(member_id, requester_partner_id)
        if error:
            return {'success': False, 'error': error}
        vals = self._clean_relative_vals(vals)
        if 'name' in vals and not vals['name']:
            return {'success': False, 'error': 'Please enter a name'}
        if 'date_of_birth' in vals:
            vals['guardian_id'] = relative.added_by_partner_id.id if self._is_minor(vals['date_of_birth']) else False
        relative.sudo().write(vals)
        return {'success': True}

    @api.model
    def app_remove_my_family_member(self, member_id, requester_partner_id=None):
        """Takes the relative out of the household. Nothing is deleted: the
        record is archived so the church keeps its history."""
        relative, error = self._my_relative(member_id, requester_partner_id)
        if error:
            return {'success': False, 'error': error}
        if relative.family_verified:
            # Confirmed by the church: just unlink from this household.
            relative.sudo().write({'family_id': False, 'is_family_head': False, 'guardian_id': False})
        else:
            relative.sudo().write({'family_id': False, 'active': False})
        return {'success': True}

    @api.model
    def app_verify_family_member(self, member_id, requester_staff_id=None):
        mode, scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        relative = self.sudo().browse(member_id)
        if not relative.exists():
            return {'success': False, 'error': 'Member not found'}
        if mode == 'assigned' and relative.id not in (scope or []) \
                and relative.added_by_partner_id.id not in (scope or []):
            return {'success': False, 'error': 'Not authorized for this member'}
        relative.sudo().write({'family_verified': True})
        return {'success': True, 'member_number': relative.member_number or ''}

    @api.model
    def app_get_member_home(self, requester_partner_id):
        """Everything the member's personal Church home screen shows, in one call."""
        mode, scope = self._church_caller_scope(requester_partner_id=requester_partner_id)
        if mode != 'self':
            return {'success': False, 'error': 'Not authorized'}
        partner = self.sudo().browse(scope)
        status_labels = dict(self._fields['membership_status'].selection)

        home = {
            'member': {
                'id': partner.id,
                'name': partner.name or '',
                'member_number': partner.member_number or '',
                'membership_status': partner.membership_status or '',
                'membership_status_label': status_labels.get(partner.membership_status, ''),
                'member_join_date': fields.Date.to_string(partner.member_join_date) if partner.member_join_date else False,
                'family': partner.family_id.name or '',
                'write_date': fields.Datetime.to_string(partner.write_date) if partner.write_date else False,
            },
            'profile_completeness': partner.profile_completeness,
            'profile_missing': partner._profile_missing(),
        }

        now = fields.Datetime.now()
        services = self.env['church.service'].sudo().search(
            [('is_active', '=', True), ('date_start', '>=', now)],
            order='date_start asc', limit=2)
        home['next_services'] = [dict({
            'id': s.id, 'name': s.name, 'location': s.location or '',
            'date_start': fields.Datetime.to_string(s.date_start),
        }, **s._rsvp_summary(partner.id)) for s in services]

        groups = self.env['cell.group'].sudo().search(
            ['|', ('leader_id', '=', partner.id), ('member_ids', '=', partner.id)])
        home['groups'] = [{
            'id': g.id, 'name': g.name,
            'leader': g.leader_id.name or '',
            'is_leader': g.leader_id.id == partner.id,
        } for g in groups]

        Prayer = self.env['prayer.request'].sudo()
        home['prayers'] = {
            'open': Prayer.search_count([
                ('partner_id', '=', partner.id),
                ('care_status', 'in', ('submitted', 'assigned', 'praying', 'follow_up'))]),
            'answered': Prayer.search_count([
                ('partner_id', '=', partner.id), ('care_status', '=', 'answered')]),
            'with_response': Prayer.search_count([
                ('partner_id', '=', partner.id), ('response', '!=', False)]),
        }

        # Pledges live in church_finance (which depends on this module), so
        # only include them when that module is installed.
        if 'church.give.pledge' in self.env:
            pledges = self.env['church.give.pledge'].sudo().search(
                [('member_id', '=', partner.id), ('status', '=', 'active')])
            home['pledges'] = {
                'active': len(pledges),
                'pledged': sum(pledges.mapped('pledge_amount')),
                'paid': sum(pledges.mapped('paid_amount')),
                'currency': pledges[:1].currency or 'PKR',
            }
        return {'success': True, 'home': home}

