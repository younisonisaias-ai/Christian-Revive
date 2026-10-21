"""Giving history and totals only for the member who gave, or for staff.

church_give answers app_get_transactions / app_get_totals for whatever
app_user_id the app sends, and with none it listed every donor's gifts.
Here the id must belong to the member signed in on the phone, or the
caller must be signed-in staff (the admin giving reports). Guests keep
their history on the phone, so an empty or 'guest' id returns nothing.
"""
from odoo import api, models


class ChurchGiveHistoryGuard(models.Model):
    _inherit = 'church.give.transaction'

    @api.model
    def _app_history_allowed(self, *args, **kwargs):
        clean = [a for a in args if a != []]
        data = kwargs if kwargs else (clean[0] if clean and isinstance(clean[0], dict) else {})
        uid = str(data.get('app_user_id') or '').strip()
        if not uid or uid == 'guest':
            return False
        if not uid.isdigit():
            # Older installs used a random id of the phone itself.
            return True
        Session = self.env['church.app.session']
        staff = Session._current_staff()
        if staff:
            return bool(staff.employee_id.is_app_active)
        member = Session._current_member()
        if member:
            return member.partner_id.id == int(uid)
        # No token: allowed only until app sessions are required.
        return not Session._required()

    @api.model
    def app_get_transactions(self, *args, **kwargs):
        if not self._app_history_allowed(*args, **kwargs):
            return []
        return super().app_get_transactions(*args, **kwargs)

    @api.model
    def app_get_totals(self, *args, **kwargs):
        if not self._app_history_allowed(*args, **kwargs):
            return {}
        return super().app_get_totals(*args, **kwargs)
