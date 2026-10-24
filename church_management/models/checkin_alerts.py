"""Tell staff when a member checks in from the app.

One push per check-in (a family checking in together is one alert) to the
church admin, the senior pastor and the pastor assigned to those members.
Only check-ins the member chose to make are announced; arriving near the
church is never reported.
"""
from odoo import api, fields, models

from .pastor_alerts import _send_fcm


class ChurchCheckinAlerts(models.Model):
    _inherit = 'church.event.attendance'

    @api.model
    def _checkin_alert_staff(self, member_ids):
        """Admins, senior pastors and the pastors assigned to these members."""
        Employee = self.env['hr.employee'].sudo()
        staff = Employee.search([
            ('is_app_active', '=', True),
            '|', ('staff_role', '=', 'admin'),
            '&', ('staff_role', '=', 'pastor'), ('is_senior_pastor', '=', True),
        ])
        staff |= self.env['pastor.assignment'].sudo().search(
            [('member_id', 'in', list(member_ids))]).mapped('pastor_id').filtered('is_app_active')
        return staff.filtered('app_fcm_token')

    @api.model
    def _alert_staff_check_in(self, acting_partner, successful):
        """successful: the 'successful' rows of a member check-in result."""
        if not successful:
            return
        by_service = {}
        for row in successful:
            by_service.setdefault(row.get('service_id'), []).append(row)
        for service_id, rows in by_service.items():
            service = self.env['church.service'].sudo().browse(service_id).exists()
            if not service:
                continue
            staff = self._checkin_alert_staff({r['member_id'] for r in rows})
            if not staff:
                continue
            names = [r.get('member_name') or '' for r in rows]
            lead = acting_partner.name if acting_partner and acting_partner.id in {r['member_id'] for r in rows} \
                else names[0]
            others = len(rows) - 1
            title = 'Checked in: %s%s' % (lead, ' +%d family' % others if others else '')
            late = any(r.get('is_late') for r in rows)
            body = '%s · %s%s' % (service.name, service._local_labels().get('time_label') or '',
                                  ' · late' if late else '')
            data = {'type': 'pastor_alert', 'kind': 'checkin', 'id': service.id}
            tokens = staff.mapped('app_fcm_token')
            sa_path = self.env['ir.config_parameter'].sudo().get_param('onevoice27.fcm_service_account_path', '')
            self.env.cr.postcommit.add(lambda t=tokens, ti=title, b=body, d=data: _send_fcm(sa_path, t, ti, b, d))

    @api.model
    def app_attendance_check_in(self, items, latitude=None, longitude=None, accuracy=None,
                                captured_at=None, device_id=None, idempotency_key=None,
                                offline=False):
        result = super().app_attendance_check_in(
            items, latitude=latitude, longitude=longitude, accuracy=accuracy,
            captured_at=captured_at, device_id=device_id, idempotency_key=idempotency_key,
            offline=offline)
        # Replays of an earlier attempt were already announced.
        if result.get('success') and result.get('successful') and not result.get('replayed'):
            try:
                self._alert_staff_check_in(self._member_from_session(), result['successful'])
            except Exception:  # noqa: BLE001 - the check-in itself must never fail
                pass
        return result
