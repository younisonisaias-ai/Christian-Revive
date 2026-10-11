"""Merge patients registered twice (same person, two records)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

COPY_IF_EMPTY = ['phone', 'date_of_birth', 'age_years', 'area', 'guardian_name']


class CampPatientMerge(models.TransientModel):
    _name = 'camp.patient.merge'
    _description = 'Merge camp patients'

    patient_ids = fields.Many2many('camp.patient', string='Patients')
    keep_id = fields.Many2one('camp.patient', string='Keep this record', required=True,
                              domain="[('id', 'in', patient_ids)]")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') == 'camp.patient' and ids:
            patients = self.env['camp.patient'].browse(ids)
            res['patient_ids'] = [(6, 0, patients.ids)]
            # Keep the one with the most visits (then the oldest).
            res['keep_id'] = max(patients, key=lambda p: (len(p.visit_ids), -p.id)).id
        return res

    def action_merge(self):
        self.ensure_one()
        keep = self.keep_id
        others = self.patient_ids - keep
        if not others:
            raise UserError(_('Choose at least two patients.'))
        camps = keep.visit_ids.camp_id
        for p in others:
            clash = p.visit_ids.camp_id & camps
            if clash:
                raise UserError(_('%(a)s and %(b)s were both registered at "%(camp)s". '
                                  'Cancel one of those two visits in that camp first.',
                                  a=keep.name, b=p.name, camp=clash[0].name))
            camps |= p.visit_ids.camp_id
        vals = {}
        for f in COPY_IF_EMPTY:
            if not keep[f]:
                vals[f] = next((p[f] for p in others if p[f]), keep[f])
        allergies = [a.strip() for p in keep | others for a in (p.allergies or '').split(',') if a.strip()]
        if allergies:
            vals['allergies'] = ', '.join(dict.fromkeys(allergies))   # all, once each
        for consent in ('consent_media', 'consent_messages'):
            vals[consent] = keep[consent] and all(p[consent] for p in others)
        keep.write(vals)
        others.visit_ids.sudo().write({'patient_id': keep.id})
        self.env['camp.reminder'].sudo().search([('patient_id', 'in', others.ids)]).write({'patient_id': keep.id})
        for p in others:
            p.write({'active': False, 'merged_into_id': keep.id})
            keep.message_post(body=_('Merged with %(name)s (%(code)s).', name=p.name, code=p.patient_code or ''))
        return {'type': 'ir.actions.act_window', 'res_model': 'camp.patient', 'res_id': keep.id,
                'view_mode': 'form', 'target': 'current'}
