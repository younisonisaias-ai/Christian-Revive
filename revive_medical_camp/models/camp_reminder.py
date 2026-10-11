"""Reminders for patients who agreed to messages. A volunteer sends each one
from their own phone (WhatsApp or SMS), so no paid messaging service is needed."""
from datetime import timedelta

from odoo import _, api, fields, models

REMINDER_KINDS = [
    ('referral', 'Go to the hospital (referral)'),
    ('medicine_end', 'Medicines finished'),
    ('next_camp', 'Next camp in your area'),
]
NEXT_CAMP_DAYS = 7      # remind patients about a camp starting within this many days
NEXT_CAMP_YEARS = 2     # patients seen in the area in the last 2 years


class CampReminder(models.Model):
    _name = 'camp.reminder'
    _description = 'Camp Reminder Message'
    _inherit = ['camp.sync.mixin']
    _order = 'due_date, id'

    camp_id = fields.Many2one('camp.camp', required=True, ondelete='cascade', index=True,
                              help='The camp whose team sends it (for "next camp": the coming camp).')
    patient_id = fields.Many2one('camp.patient', required=True, ondelete='cascade', index=True)
    phone = fields.Char(related='patient_id.phone')
    visit_id = fields.Many2one('camp.visit', ondelete='cascade')
    referral_id = fields.Many2one('camp.referral', ondelete='cascade')
    kind = fields.Selection(REMINDER_KINDS, required=True)
    message = fields.Text(required=True)
    due_date = fields.Date(required=True, index=True)
    state = fields.Selection([('to_send', 'To send'), ('sent', 'Sent'), ('skipped', 'Not sent')],
                             default='to_send', required=True, index=True)
    sent_by_id = fields.Many2one('res.users', readonly=True)
    sent_at = fields.Datetime(readonly=True)

    _once = models.Constraint('UNIQUE(camp_id, patient_id, kind, referral_id, visit_id)',
                              'This reminder already exists.')

    @api.depends('patient_id', 'kind')
    def _compute_display_name(self):
        kinds = dict(REMINDER_KINDS)
        for r in self:
            r.display_name = f'{r.patient_id.name or ""}: {kinds.get(r.kind, "")}'

    # ── Making the reminders ───────────────────────────────────
    @api.model
    def _make(self, camp, patient, kind, message, due, visit=None, referral=None):
        if not patient.consent_messages or not (patient.phone or '').strip():
            return self
        domain = [('camp_id', '=', camp.id), ('patient_id', '=', patient.id), ('kind', '=', kind),
                  ('visit_id', '=', visit.id if visit else False),
                  ('referral_id', '=', referral.id if referral else False)]
        if self.sudo().search_count(domain):
            return self
        return self.sudo().create({
            'camp_id': camp.id, 'patient_id': patient.id, 'kind': kind, 'message': message, 'due_date': due,
            'visit_id': visit.id if visit else False, 'referral_id': referral.id if referral else False,
        })

    @api.model
    def _generate(self, camps=None):
        """Create due reminders. Safe to run again: each reminder is made once."""
        today = fields.Date.context_today(self)
        Camp = self.env['camp.camp'].sudo()
        camps = camps.sudo() if camps else Camp.search([])

        # Referral: the day after the letter, if the hospital has not confirmed.
        for r in self.env['camp.referral'].sudo().search(
                [('camp_id', 'in', camps.ids), ('status', '=', 'issued')]):
            due = (r.create_date.date() if r.create_date else today) + timedelta(days=1)
            msg = _('Assalam-o-Alaikum %(name)s. Please go to %(hospital)s%(dept)s as the camp doctor advised. '
                    'Take your referral letter with you.\n'
                    'السلام علیکم۔ کیمپ کے ڈاکٹر کے مشورے کے مطابق براہ کرم %(hospital)s جائیں۔ ریفرل لیٹر ساتھ لے جائیں۔',
                    name=r.patient_id.name, hospital=r.hospital_id.name,
                    dept=f' ({r.department})' if r.department else '')
            self._make(r.camp_id, r.patient_id, 'referral', msg, due, referral=r)

        # Medicines finished: the day after the longest course ends.
        for c in self.env['camp.consultation'].sudo().search(
                [('camp_id', 'in', camps.ids), ('state', '=', 'done')]):
            given = c.prescription_line_ids.filtered(lambda l: l.dispensed_qty > 0)
            if not given:
                continue
            start = (c.visit_id.arrived_at or c.create_date).date()
            due = start + timedelta(days=max(given.mapped('days') or [1]) + 1)
            msg = _('Assalam-o-Alaikum %(name)s. Your medicines from the medical camp should be finished now. '
                    'If you are not better, please see a doctor.\n'
                    'السلام علیکم۔ میڈیکل کیمپ کی دوائیں اب ختم ہو گئی ہوں گی۔ اگر طبیعت بہتر نہیں تو ڈاکٹر کو دکھائیں۔',
                    name=c.patient_id.name)
            self._make(c.camp_id, c.patient_id, 'medicine_end', msg, due, visit=c.visit_id)

        # Next camp: patients seen in the area before, a few days before it starts.
        soon = Camp.search([('state', 'in', ('draft', 'ready')), ('date_start', '>=', today),
                            ('date_start', '<=', today + timedelta(days=NEXT_CAMP_DAYS)), ('area', '!=', False)])
        api_model = self.env['camp.api'].sudo()
        for camp in soon:
            patients = self.env['camp.patient'].sudo().search(api_model._returning_domain(camp))
            due = max(today, camp.date_start - timedelta(days=2))
            for p in patients:
                msg = _('Assalam-o-Alaikum %(name)s. A free medical camp is coming to %(site)s on %(date)s. '
                        'Please come and bring your old camp card or slip.\n'
                        'السلام علیکم۔ مفت میڈیکل کیمپ %(date)s کو %(site)s میں لگ رہا ہے۔ تشریف لائیں اور پرانا کیمپ کارڈ ساتھ لائیں۔',
                        name=p.name, site=camp.site or camp.area, date=camp.date_start.strftime('%d %b'))
                self._make(camp, p, 'next_camp', msg, due)
        return True

    @api.model
    def _cron_generate(self):
        recent = fields.Date.context_today(self) - timedelta(days=60)
        camps = self.env['camp.camp'].sudo().search(['|', ('state', '!=', 'closed'), ('date_start', '>=', recent)])
        return self._generate(camps)

    def mark(self, result):
        self.write({'state': result, 'sent_by_id': self.env.user.id, 'sent_at': fields.Datetime.now()})
