"""Public page for hospitals: scan the QR code on a referral letter and
confirm the patient arrived. The link holds a long random code, so only the
person holding the letter can open it."""
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

LINK_DAYS = 30          # the link works for 30 days after the referral
BAD_CODES_PER_HOUR = 20


def _render(values, status=200):
    resp = request.render('revive_medical_camp.referral_confirm_page', values, status=status)
    resp.headers['X-Robots-Tag'] = 'noindex, nofollow'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


class CampReferralPage(http.Controller):

    def _referral(self, code):
        """(referral, state): state is ok, expired, closed (already confirmed), invalid or blocked."""
        Referral = request.env['camp.referral']
        ip = request.httprequest.remote_addr or '?'
        throttle = request.env['camp.auth.throttle']
        blocked_key = f'refcode:{ip}'
        row = throttle.sudo().search([('key', '=', blocked_key)], limit=1)
        if row and row.failures > BAD_CODES_PER_HOUR and row.window_start and \
                row.window_start > fields.Datetime.now() - timedelta(hours=1):
            return Referral, 'blocked'
        referral = Referral.sudo().search([('confirm_code', '=', code)], limit=1) if code and len(code) >= 20 else Referral
        if not referral:
            throttle.hit(blocked_key, BAD_CODES_PER_HOUR)
            return Referral, 'invalid'
        if referral.status != 'issued':
            return referral, 'closed'
        if referral.create_date and referral.create_date < fields.Datetime.now() - timedelta(days=LINK_DAYS):
            return referral, 'expired'
        return referral, 'ok'

    @http.route('/camp/referral/<string:code>', type='http', auth='public', methods=['GET'], website=False)
    def show(self, code, **kwargs):
        referral, state = self._referral(code)
        # Patient details only while the link is open (not after it is used or old).
        return _render({'r': referral if state == 'ok' else referral.browse(), 'state': state, 'done': False,
                        'confirmed': referral if state == 'closed' else referral.browse()},
                       status=429 if state == 'blocked' else 200)

    @http.route('/camp/referral/<string:code>', type='http', auth='public', methods=['POST'], csrf=True)
    def confirm(self, code, received_by='', **kwargs):
        referral, state = self._referral(code)
        if state == 'ok':
            referral._confirm_arrival((received_by or '').strip()[:80])
            return _render({'r': referral.browse(), 'state': 'closed', 'done': True, 'confirmed': referral})
        return _render({'r': referral.browse(), 'state': state, 'done': False,
                        'confirmed': referral if state == 'closed' else referral.browse()},
                       status=429 if state == 'blocked' else 200)
