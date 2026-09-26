from odoo import models, fields, api


class HrEmployeeSeniorPastor(models.Model):
    _inherit = 'hr.employee'

    is_senior_pastor = fields.Boolean(
        string='Senior Pastor',
        help='Senior pastors see every member in the church. '
             'Associate/assistant pastors see only members explicitly '
             'assigned to them under Church Management > Pastor Assignments.',
    )

    # Edit a pastor's members all at once (pick many from a list). Reads and
    # writes the same pastor.assignment records the app and scoping use.
    assigned_member_ids = fields.Many2many(
        'res.partner', string='Assigned Members',
        compute='_compute_assigned_members', inverse='_inverse_assigned_members',
        domain=[('is_member', '=', True)])
    assigned_member_count = fields.Integer(
        string='Members', compute='_compute_assigned_members')

    def _compute_assigned_members(self):
        Assignment = self.env['pastor.assignment'].sudo()
        for employee in self:
            pastor_id = employee._origin.id
            members = Assignment.search([('pastor_id', '=', pastor_id)]).mapped('member_id') \
                if pastor_id else self.env['res.partner']
            employee.assigned_member_ids = members
            employee.assigned_member_count = len(members)

    def _inverse_assigned_members(self):
        Assignment = self.env['pastor.assignment'].sudo()
        for employee in self:
            pastor_id = employee._origin.id or employee.id
            current = Assignment.search([('pastor_id', '=', pastor_id)])
            wanted = employee.assigned_member_ids
            current.filtered(lambda a: a.member_id not in wanted).unlink()
            already = current.mapped('member_id')
            Assignment.create([
                {'pastor_id': pastor_id, 'member_id': member.id}
                for member in wanted - already
            ])


class PastorAssignment(models.Model):
    _name = 'pastor.assignment'
    _description = 'Pastor to Member Assignment'
    _order = 'pastor_id, member_id'
    _rec_name = 'member_id'

    pastor_id = fields.Many2one(
        'hr.employee', string='Pastor', required=True,
        domain=[('staff_role', '=', 'pastor')],
    )
    member_id = fields.Many2one(
        'res.partner', string='Member', required=True,
        domain=[('is_member', '=', True)],
    )
    assigned_date = fields.Date(string='Assigned On', default=fields.Date.context_today)
    notes = fields.Char(string='Notes')

    _sql_constraints = [
        ('pastor_member_uniq', 'unique(pastor_id, member_id)',
         'This member is already assigned to this pastor.'),
    ]

    # ── Church Management RPC ────────────────────────────────────
    # Assigning pastors controls who can see which members' data, so this
    # is restricted to mode='all' (church admin / senior pastor) only —
    # not the relaxed 'assigned' scope used for member/family management.

    @api.model
    def app_get_pastors(self, requester_staff_id=None):
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_staff_id=requester_staff_id)
        if mode != 'all':
            return {'success': False, 'error': 'Not authorized'}
        pastors = self.env['hr.employee'].sudo().search(
            [('staff_role', '=', 'pastor')], order='name')
        return {'success': True, 'pastors': [{
            'id': p.id, 'name': p.name,
            'is_senior_pastor': p.is_senior_pastor,
        } for p in pastors]}

    @api.model
    def app_get_pastor_assignments(self, requester_staff_id=None):
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_staff_id=requester_staff_id)
        if mode != 'all':
            return {'success': False, 'error': 'Not authorized'}
        assignments = self.sudo().search([], order='pastor_id, member_id')
        return {'success': True, 'assignments': [{
            'id': a.id,
            'pastor_id': a.pastor_id.id, 'pastor_name': a.pastor_id.name,
            'member_id': a.member_id.id, 'member_name': a.member_id.name,
            'assigned_date': a.assigned_date.isoformat() if a.assigned_date else '',
        } for a in assignments]}

    @api.model
    def app_assign_pastor(self, pastor_id, member_id, requester_staff_id=None):
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_staff_id=requester_staff_id)
        if mode != 'all':
            return {'success': False, 'error': 'Not authorized'}
        existing = self.sudo().search([
            ('pastor_id', '=', pastor_id), ('member_id', '=', member_id),
        ], limit=1)
        if existing:
            return {'success': False, 'error': 'This member is already assigned to this pastor'}
        assignment = self.sudo().create({'pastor_id': pastor_id, 'member_id': member_id})
        return {'success': True, 'assignment_id': assignment.id}

    @api.model
    def app_remove_pastor_assignment(self, assignment_id, requester_staff_id=None):
        mode, _scope = self.env['res.partner']._church_caller_scope(
            requester_staff_id=requester_staff_id)
        if mode != 'all':
            return {'success': False, 'error': 'Not authorized'}
        assignment = self.sudo().browse(assignment_id)
        if assignment.exists():
            assignment.unlink()
        return {'success': True}
