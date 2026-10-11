"""Public page for hospitals: scan the QR code on a referral letter and
confirm the patient arrived. The link holds a long random code, so only the
person holding the letter can open it."""
from odoo import fields, http
from odoo.http import request


class CampReferralPage(http.Controller):

    def _referral(self, code):
        if not code or len(code) < 20:
            return request.env['camp.referral']
        return request.env['camp.referral'].sudo().search([('confirm_code', '=', code)], limit=1)

    @http.route('/camp/referral/<string:code>', type='http', auth='public', methods=['GET'], website=False)
    def show(self, code, **kwargs):
        referral = self._referral(code)
        return request.render('revive_medical_camp.referral_confirm_page', {'r': referral, 'done': False})

    @http.route('/camp/referral/<string:code>', type='http', auth='public', methods=['POST'], csrf=True)
    def confirm(self, code, received_by='', **kwargs):
        referral = self._referral(code)
        if referral and referral.status == 'issued':
            referral._confirm_arrival((received_by or '').strip()[:80])
        return request.render('revive_medical_camp.referral_confirm_page', {'r': referral, 'done': True})
