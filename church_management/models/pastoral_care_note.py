from odoo import models, fields, api


class PastoralCareNote(models.Model):
    _name = 'pastoral.care.note'
    _description = 'Pastoral Care Note'
    _order = 'date desc'

    # SECURITY NOTE: this note's `content` is sensitive (counseling/prayer
    # records) and access below is strictly scoped in Python to the
    # author and senior pastors/admins — nobody else can reach it through
    # the app_* RPC layer. It is NOT yet encrypted at rest in Postgres
    # (that needs pgcrypto or a Python crypto lib added to Dockerfile.odoo,
    # which isn't currently installed — an infra change, not a code change,
    # left for a deliberate follow-up rather than made silently here).

    member_id = fields.Many2one(
        'res.partner', string='Member', required=True,
        domain=[('is_member', '=', True)],
    )
    author_id = fields.Many2one(
        'hr.employee', string='Author', required=True,
        domain=[('staff_role', '=', 'pastor')],
    )
    note_type = fields.Selection([
        ('visit', 'Home Visit'),
        ('hospital', 'Hospital Visit'),
        ('bereavement', 'Bereavement Visit'),
        ('call', 'Phone Call'),
        ('counseling', 'Counseling Session'),
        ('prayer', 'Prayer Request'),
        ('other', 'Other'),
    ], string='Type', default='visit', required=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    content = fields.Text(string='Notes', required=True)
    outcome = fields.Text(string='Outcome')
    is_urgent = fields.Boolean(string='Urgent')
    follow_up_date = fields.Date(string='Follow-up Date')
    follow_up_assigned_to_id = fields.Many2one(
        'hr.employee', string='Follow-up By',
        domain=[('staff_role', 'in', ('pastor', 'admin'))],
        help='Who should do the follow-up. Leave empty for the author.')
    follow_up_done = fields.Boolean(string='Follow-up Done')
    visible_to_senior_pastor_only = fields.Boolean(
        string='Restrict to Author + Senior Pastor', default=True,
        help='If off, any pastor with access to this member can read the note.',
    )

    _APP_NOTE_FIELDS = {
        'note_type', 'date', 'content', 'outcome', 'is_urgent', 'follow_up_date',
        'follow_up_assigned_to_id', 'visible_to_senior_pastor_only',
    }

    # ── Church Management RPC (Phase 2) ─────────────────────────

    def _pastoral_access(self, requester_staff_id):
        """(employee, is_senior_or_admin) for the calling staff member, or
        (None, False) if requester_staff_id doesn't resolve to live staff."""
        if not requester_staff_id:
            return None, False
        employee = self.env['hr.employee'].sudo().browse(requester_staff_id)
        if not employee.exists() or not employee.is_app_active:
            return None, False
        is_senior_or_admin = employee.staff_role == 'admin' or (
            employee.staff_role == 'pastor' and employee.is_senior_pastor
        )
        return employee, is_senior_or_admin

    @api.model
    def app_get_pastoral_notes(self, member_id, requester_staff_id=None):
        employee, is_senior_or_admin = self._pastoral_access(requester_staff_id)
        if not employee or employee.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Not authorized'}

        domain = [('member_id', '=', member_id)]
        if not is_senior_or_admin:
            # An associate pastor only sees their own notes, plus any note
            # another pastor explicitly opened up beyond author-only.
            domain += ['|', ('author_id', '=', employee.id),
                       ('visible_to_senior_pastor_only', '=', False)]

        notes = self.sudo().search(domain, order='date desc')
        return {'success': True, 'notes': notes.read([
            'id', 'note_type', 'date', 'content', 'outcome', 'is_urgent',
            'follow_up_date', 'follow_up_done', 'follow_up_assigned_to_id',
            'author_id', 'visible_to_senior_pastor_only',
        ])}

    @api.model
    def app_add_pastoral_note(self, member_id, vals, requester_staff_id=None):
        employee, _is_senior = self._pastoral_access(requester_staff_id)
        if not employee or employee.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Not authorized'}

        vals = {k: v for k, v in dict(vals or {}).items() if k in self._APP_NOTE_FIELDS}
        vals['member_id'] = member_id
        vals['author_id'] = employee.id
        note = self.sudo().create(vals)
        return {'success': True, 'note_id': note.id}

    def _follow_up_domain(self, employee, is_senior_or_admin):
        domain = [('follow_up_date', '!=', False), ('follow_up_done', '=', False)]
        if not is_senior_or_admin:
            domain += ['|', ('follow_up_assigned_to_id', '=', employee.id),
                       '&', ('follow_up_assigned_to_id', '=', False),
                       ('author_id', '=', employee.id)]
        return domain

    @api.model
    def app_get_my_follow_ups(self, requester_staff_id, days_ahead=7):
        """Open follow-ups that are overdue, due today, or due in the next
        `days_ahead` days, soonest first."""
        employee, is_senior_or_admin = self._pastoral_access(requester_staff_id)
        if not employee or employee.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Not authorized'}

        today = fields.Date.context_today(self)
        horizon = fields.Date.add(today, days=days_ahead or 0)
        domain = self._follow_up_domain(employee, is_senior_or_admin)
        domain.append(('follow_up_date', '<=', horizon))
        notes = self.sudo().search(domain, order='follow_up_date, is_urgent desc')
        rows = notes.read([
            'id', 'member_id', 'note_type', 'follow_up_date', 'content',
            'is_urgent', 'author_id', 'follow_up_assigned_to_id',
        ])
        for row, note in zip(rows, notes):
            row['is_overdue'] = note.follow_up_date < today
        return {'success': True, 'follow_ups': rows}

    @api.model
    def app_complete_follow_up(self, note_id, outcome='', next_follow_up_date=None,
                               requester_staff_id=None):
        """Record the outcome of a follow-up. With `next_follow_up_date` the
        follow-up is rescheduled instead of closed."""
        employee, is_senior_or_admin = self._pastoral_access(requester_staff_id)
        if not employee or employee.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Not authorized'}
        note = self.sudo().browse(int(note_id)).exists()
        if not note:
            return {'success': False, 'error': 'Follow-up not found'}
        if not is_senior_or_admin and employee not in (
                note.author_id | note.follow_up_assigned_to_id):
            return {'success': False, 'error': 'Not authorized for this follow-up'}

        outcome = (outcome or '').strip()
        if outcome:
            stamp = '%s – %s: %s' % (fields.Date.context_today(self), employee.name, outcome)
            outcome = '%s\n%s' % (note.outcome, stamp) if note.outcome else stamp
        vals = {'outcome': outcome or note.outcome}
        if next_follow_up_date:
            vals.update({'follow_up_date': next_follow_up_date, 'follow_up_done': False})
        else:
            vals['follow_up_done'] = True
        note.write(vals)
        return {'success': True}

    @api.model
    def app_get_care_summary(self, requester_staff_id):
        """Counts for the Pastoral Care screen."""
        employee, is_senior_or_admin = self._pastoral_access(requester_staff_id)
        if not employee or employee.staff_role not in ('pastor', 'admin'):
            return {'success': False, 'error': 'Not authorized'}

        today = fields.Date.context_today(self)
        Partner = self.env['res.partner'].sudo()
        mode, scope = Partner._church_caller_scope(requester_staff_id=employee.id)
        member_domain = [('is_member', '=', True)]
        if mode == 'assigned':
            member_domain.append(('id', 'in', scope or [0]))

        follow_ups = self.sudo().search(self._follow_up_domain(employee, is_senior_or_admin))
        visit_domain = [('note_type', 'in', ('visit', 'hospital', 'bereavement')),
                        ('date', '>=', fields.Date.subtract(today, days=7))]
        if not is_senior_or_admin:
            visit_domain.append(('author_id', '=', employee.id))

        Prayer = self.env['prayer.request']
        pastor, sees_everything, members = Prayer._care_staff(employee.id)
        prayer_domain = Prayer._care_domain(pastor, sees_everything, members) + [
            ('care_status', 'in', ('submitted', 'assigned', 'praying', 'follow_up'))]

        return {'success': True, 'summary': {
            'members': Partner.search_count(member_domain),
            'needs_attention': Partner.search_count(member_domain + [
                ('care_status', 'not in', ('healthy', 'new_member', False))]),
            'follow_ups_due': len(follow_ups.filtered(lambda n: n.follow_up_date <= today)),
            'follow_ups_upcoming': len(follow_ups.filtered(lambda n: n.follow_up_date > today)),
            'visits_this_week': self.sudo().search_count(visit_domain),
            'open_prayers': Prayer.sudo().search_count(prayer_domain),
            'urgent_prayers': Prayer.sudo().search_count(prayer_domain + [('urgency', '=', 'urgent')]),
        }}
