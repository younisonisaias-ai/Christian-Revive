"""First-time visitors: recorded at the door, followed up by a pastor, and
tracked until they attend regularly or become members."""
from odoo import api, fields, models

VISITOR_STAGES = [
    ('new', 'First visit'),
    ('contacted', 'Followed up'),
    ('returning', 'Attending again'),
    ('joined', 'Became a member'),
    ('not_interested', 'Not continuing'),
]

VISITOR_SOURCES = [
    ('friend', 'Friend'),
    ('family', 'Family'),
    ('social', 'Social media / online'),
    ('event', 'Church event'),
    ('walk_in', 'Walked in'),
    ('other', 'Other'),
]

FOLLOW_UP_AFTER_DAYS = 3


class ResPartnerVisitor(models.Model):
    _inherit = 'res.partner'

    visitor_stage = fields.Selection(VISITOR_STAGES, string='Visitor Stage', index=True,
                                     help='Set for people first recorded as visitors.')
    visitor_source = fields.Selection(VISITOR_SOURCES, string='How They Heard')
    first_visit_date = fields.Date(string='First Visit')
    visitor_notes = fields.Text(string='Visitor Notes')
    visitor_added_by_id = fields.Many2one('hr.employee', string='Welcomed By', readonly=True)

    def _visitor_dict(self):
        self.ensure_one()
        stages = dict(VISITOR_STAGES)
        sources = dict(VISITOR_SOURCES)
        visits = self.env['church.event.attendance'].sudo().search_count([('member_id', '=', self.id)])
        return {
            'id': self.id,
            'name': self.name or '',
            'phone': self.phone or '',
            'email': self.email or '',
            'stage': self.visitor_stage or '',
            'stage_label': stages.get(self.visitor_stage, ''),
            'source': self.visitor_source or '',
            'source_label': sources.get(self.visitor_source, ''),
            'first_visit_date': fields.Date.to_string(self.first_visit_date) if self.first_visit_date else '',
            'visits': visits,
            'notes': self.visitor_notes or '',
            'welcomed_by': self.visitor_added_by_id.name or '',
        }

    @api.model
    def app_add_visitor(self, vals, service_id=None, requester_staff_id=None):
        """Usher/pastor records a first-time visitor, checks them in to the
        service, and gets a follow-up task in 3 days."""
        mode, _scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        vals = dict(vals or {})
        name = (vals.get('name') or '').strip()
        if not name:
            return {'success': False, 'error': 'Please enter a name'}
        source = vals.get('source') if vals.get('source') in dict(VISITOR_SOURCES) else False
        today = fields.Date.context_today(self)
        staff = self.env['hr.employee'].sudo().browse(int(requester_staff_id))
        visitor = self.sudo().create({
            'name': name,
            'phone': (vals.get('phone') or '').strip() or False,
            'email': (vals.get('email') or '').strip() or False,
            'membership_status': 'visitor',
            'visitor_stage': 'new',
            'visitor_source': source,
            'first_visit_date': today,
            'visitor_notes': (vals.get('notes') or '').strip() or False,
            'visitor_added_by_id': staff.id,
        })
        if staff.staff_role == 'pastor':
            self.env['pastor.assignment'].sudo().create({
                'pastor_id': staff.id, 'member_id': visitor.id, 'notes': 'First-time visitor'})
        self.env['pastoral.care.note'].sudo().create({
            'member_id': visitor.id,
            'author_id': staff.id,
            'note_type': 'call',
            'content': f'Welcome call for first-time visitor {name}.'
                       + (f' Heard about us from: {dict(VISITOR_SOURCES)[source]}.' if source else ''),
            'follow_up_date': fields.Date.add(today, days=FOLLOW_UP_AFTER_DAYS),
            'follow_up_assigned_to_id': staff.id,
            'visible_to_senior_pastor_only': False,
        })
        checked_in = False
        if service_id:
            result = self.env['church.event.attendance'].app_check_in(
                member_id=visitor.id, service_id=service_id,
                requester_staff_id=requester_staff_id, method='manual')
            checked_in = bool(result.get('success'))
        return {'success': True, 'visitor_id': visitor.id, 'checked_in': checked_in}

    @api.model
    def app_get_visitors(self, requester_staff_id=None, stage=None):
        mode, scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        domain = [('visitor_stage', '!=', False)]
        if mode == 'assigned':
            domain += ['|', ('id', 'in', scope or [0]), ('visitor_added_by_id', '=', int(requester_staff_id))]
        everyone = self.sudo().search(domain, order='first_visit_date desc, id desc', limit=500)
        counts = {key: 0 for key, _label in VISITOR_STAGES}
        for v in everyone:
            counts[v.visitor_stage] = counts.get(v.visitor_stage, 0) + 1
        visitors = everyone.filtered(lambda v: v.visitor_stage == stage) if stage else everyone
        return {'success': True, 'visitors': [v._visitor_dict() for v in visitors], 'counts': counts,
                'stages': [{'key': k, 'label': l} for k, l in VISITOR_STAGES]}

    @api.model
    def app_update_visitor(self, visitor_id, vals, requester_staff_id=None):
        mode, scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Not authorized'}
        visitor = self.sudo().browse(int(visitor_id)).exists()
        if not visitor or not visitor.visitor_stage:
            return {'success': False, 'error': 'Visitor not found'}
        if mode == 'assigned' and visitor.id not in (scope or []) \
                and visitor.visitor_added_by_id.id != int(requester_staff_id):
            return {'success': False, 'error': 'Not authorized for this visitor'}
        vals = dict(vals or {})
        write = {}
        if vals.get('stage') in dict(VISITOR_STAGES):
            write['visitor_stage'] = vals['stage']
            if vals['stage'] == 'joined':
                # Becomes a church member (gets a member number).
                write.update({'is_member': True, 'membership_status': 'member',
                              'member_join_date': fields.Date.context_today(self)})
        if 'notes' in vals:
            write['visitor_notes'] = (vals.get('notes') or '').strip() or False
        if 'phone' in vals:
            write['phone'] = (vals.get('phone') or '').strip() or False
        if write:
            visitor.write(write)
        return {'success': True, 'visitor': visitor._visitor_dict()}
