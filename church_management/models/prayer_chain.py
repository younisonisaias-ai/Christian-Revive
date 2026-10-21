"""Prayer chain: members ticked as Prayer Team get an alert as soon as an
urgent prayer request is shared with the church or the prayer team.
Requests kept for pastors only, or private, never reach the team.
"""
from odoo import api, fields, models

from .pastor_alerts import _send_fcm

SHARED_WITH_TEAM = ('public', 'prayer_team')


class ResPartnerPrayerTeam(models.Model):
    _inherit = 'res.partner'

    prayer_team = fields.Boolean(
        string='Prayer Team', help='Gets an alert for every urgent prayer request shared with the church.')

    @api.model
    def app_set_prayer_team(self, member_id, on, requester_staff_id=None):
        """Staff: add a member to the prayer chain or take them off it."""
        mode, scope = self._church_caller_scope(requester_staff_id=requester_staff_id)
        if mode not in ('all', 'assigned'):
            return {'success': False, 'error': 'Only staff can change the prayer team'}
        member = self.sudo().browse(int(member_id or 0)).exists()
        if not member or (mode == 'assigned' and member.id not in (scope or [])):
            return {'success': False, 'error': 'Member not found'}
        member.prayer_team = bool(on)
        return {'success': True, 'prayer_team': member.prayer_team}


class PrayerRequestChain(models.Model):
    _inherit = 'prayer.request'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.urgency == 'urgent' and rec.visibility in SHARED_WITH_TEAM:
                rec._alert_prayer_team()
        return records

    def _alert_prayer_team(self):
        self.ensure_one()
        if not self.env['church.plan']._allows('premium'):
            return
        team = self.env['res.partner'].sudo().search([('prayer_team', '=', True), ('app_fcm_token', '!=', False)])
        team -= self.partner_id
        tokens = list(set(team.mapped('app_fcm_token')))
        if not tokens:
            return
        who = 'Someone' if getattr(self, 'is_anonymous', False) else (self.name or 'Someone')
        body = '%s asks for urgent prayer: %s' % (who, self.subject or '')
        sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
        data = {'type': 'prayer_chain', 'id': self.id}
        self.env.cr.postcommit.add(lambda: _send_fcm(sa_path, tokens, 'Urgent prayer', body, data))
