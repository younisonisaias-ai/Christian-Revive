"""The church's plan (Basic / Premium / Enterprise, plus add-ons) on the
server, so a client app cannot use features its church has not bought.

Each church runs its own ERP, so the plan is one system setting, set under
Settings → Church. With no setting the ERP behaves as Enterprise, so an
existing church loses nothing.

When the registry loads, every app endpoint listed in FEATURES is wrapped
with a plan check. Only `app_*` methods are touched, never the ERP's own
screens. The table mirrors `Features` in the plan apps (revive_core
lib/plan.dart); keep the two in step.
"""
import functools
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PLAN_PARAM = 'church_management.plan'
LEVELS = {'basic': 0, 'premium': 1, 'enterprise': 2}
NOT_IN_PLAN = "This feature is not part of your church's plan."

# What each endpoint needs: 'premium', 'enterprise', or an add-on ('giving',
# 'books'). Unlisted endpoints are Basic (sign-in, prayer, devotionals...).
# '*' means every app_* method on that model.
FEATURES = {
    # Church Management (Premium): members, families, visitors, QR check-in.
    'res.partner': {
        'premium': ['app_add_visitor', 'app_create_member', 'app_get_member_detail', 'app_get_member_home',
                    'app_get_members', 'app_get_visitors', 'app_update_member', 'app_update_visitor',
                    'app_verify_family_member', 'app_get_my_family', 'app_add_my_family_member',
                    'app_update_my_family_member', 'app_remove_my_family_member',
                    'app_set_prayer_team'],
    },
    'church.family': {'premium': ['*']},
    'church.service': {'premium': ['*']},
    'church.dashboard': {
        'premium': ['app_get_dashboard'],
        'enterprise': ['app_get_absent_members', 'app_report_manifest', 'app_report_page',
                       'app_report_member_search', 'app_pastor_week', 'app_care_report'],
    },
    'church.event.attendance': {
        'premium': ['app_check_in', 'app_get_event_attendance', 'app_get_my_attendance'],
        # Smart Attendance: Enterprise.
        'enterprise': ['app_attendance_add_guest', 'app_attendance_check_in', 'app_attendance_home',
                       'app_attendance_my_history', 'app_attendance_search_people',
                       'app_attendance_service_detail', 'app_attendance_staff_check_in',
                       'app_attendance_staff_services', 'app_attendance_update'],
    },
    'church.bulk.message': {'premium': ['*']},
    'church.visit.request': {'premium': ['*']},
    'pastor.assignment': {
        'premium': ['app_get_pastors'],  # handing a visit to another pastor
        'enterprise': ['app_assign_pastor', 'app_get_pastor_assignments', 'app_remove_pastor_assignment',
                       'app_member_care_info'],
    },
    'prayer.request': {
        'premium': ['app_get_my_prayers'],
        'enterprise': ['app_get_care_prayers', 'app_update_care_prayer'],
    },
    # Enterprise: pastoral care, cell groups, finance, operations, reports.
    'cell.group': {'enterprise': ['*']},
    'pastoral.care.note': {'enterprise': ['*']},
    'church.expense': {'enterprise': ['*']},
    'church.give.reconciliation.batch': {'enterprise': ['*']},
    'church.operations': {'enterprise': ['*']},
    'church.report': {'enterprise': ['*']},
    # Giving: Premium, or the Basic add-on.
    'church.give.transaction': {'giving': ['*']},
    'church.give.fund': {'giving': ['*']},
    'church.give.pledge': {'giving': ['*']},
    # Book library: Premium add-on, included in Enterprise.
    'library.book': {'books': ['*']},
}

# Endpoints the app reads as a list or a map rather than {'success': ...}.
EMPTY_ANSWER = {
    ('church.give.transaction', 'app_get_transactions'): list,
    ('church.give.transaction', 'app_get_totals'): dict,
    ('church.give.transaction', 'app_get_projects'): list,
}


class ChurchPlan(models.AbstractModel):
    _name = 'church.plan'
    _description = 'Church plan'

    @api.model
    def _plan(self):
        value = (self.env['ir.config_parameter'].sudo().get_param(PLAN_PARAM) or 'enterprise').lower()
        return value if value in LEVELS else 'enterprise'

    @api.model
    def _addon(self, name):
        value = self.env['ir.config_parameter'].sudo().get_param('church_management.addon_%s' % name) or ''
        return value.lower() in ('1', 'true', 'yes')

    @api.model
    def _allows(self, need):
        level = LEVELS[self._plan()]
        if need == 'giving':
            return level >= LEVELS['premium'] or self._addon('giving')
        if need == 'books':
            return level >= LEVELS['enterprise'] or (level >= LEVELS['premium'] and self._addon('books'))
        return level >= LEVELS.get(need, 0)

    @api.model
    def app_get_plan(self):
        """What this church's server allows, for the app to show or hide."""
        return {'success': True, 'plan': self._plan(),
                'addons': [a for a in ('giving', 'books') if self._addon(a)]}

    # ── Wrapping the endpoints ──────────────────────────────────

    def _register_hook(self):
        super()._register_hook()
        wrapped = 0
        for model_name, needs in FEATURES.items():
            if model_name not in self.env:
                continue  # module not installed here
            cls = type(self.env[model_name])
            for need, methods in needs.items():
                names = [n for n in dir(cls) if n.startswith('app_')] if methods == ['*'] else methods
                for name in names:
                    original = getattr(cls, name, None)
                    if not callable(original) or getattr(original, '_church_plan_need', None):
                        continue
                    setattr(cls, name, _plan_checked(original, model_name, name, need))
                    wrapped += 1
        _logger.info('Church plan %s: %d app endpoints checked', self._plan(), wrapped)


def _plan_checked(original, model_name, method_name, need):
    @functools.wraps(original)
    def checked(self, *args, **kwargs):
        if not self.env['church.plan']._allows(need):
            empty = EMPTY_ANSWER.get((model_name, method_name))
            if empty:
                return empty()
            return {'success': False, 'error': NOT_IN_PLAN, 'code': 'plan'}
        return original(self, *args, **kwargs)
    checked._church_plan_need = need
    return checked


class ResConfigSettingsChurch(models.TransientModel):
    _inherit = 'res.config.settings'

    church_plan = fields.Selection(
        [('basic', 'Basic'), ('premium', 'Premium'), ('enterprise', 'Enterprise')],
        string='Church plan', config_parameter=PLAN_PARAM, default='enterprise',
        help='Features above this plan are refused to the app.')
    church_addon_giving = fields.Boolean(
        string='Giving add-on', config_parameter='church_management.addon_giving',
        help='Online giving, pledges and funds on the Basic plan.')
    church_addon_books = fields.Boolean(
        string='Book library add-on', config_parameter='church_management.addon_books',
        help='Book and study library on the Premium plan.')
    church_topic_prefix = fields.Char(
        string='Notification topic prefix', config_parameter='revive.topic_prefix', default='revive',
        help="Must match this church's app (APP_TOPIC_PREFIX), e.g. revive_premium. Announcements go to "
             '<prefix>_all.')
    church_require_app_session = fields.Boolean(
        string='Require secure sign-in', config_parameter='church_management.require_app_session',
        help='Turn on once most members have the latest app. Members on older versions are asked '
             'to update and sign in again.')
