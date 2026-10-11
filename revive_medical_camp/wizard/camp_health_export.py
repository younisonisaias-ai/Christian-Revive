"""Monthly counts for the district health office: patients and diagnoses by
age group and sex, as an Excel or CSV file. Counts only, no names."""
import base64
import csv
import io
from datetime import date

from dateutil.relativedelta import relativedelta

from odoo import _, fields, models
from odoo.exceptions import UserError

AGE_GROUPS = [('<1', 0, 0), ('1-4', 1, 4), ('5-14', 5, 14), ('15-49', 15, 49), ('50+', 50, 200)]
SEXES = [('male', 'M'), ('female', 'F')]


def _age_group(age):
    for label, lo, hi in AGE_GROUPS:
        if lo <= (age or 0) <= hi:
            return label
    return '50+'


class CampHealthExport(models.TransientModel):
    _name = 'camp.health.export'
    _description = 'Health office export'

    date_from = fields.Date(required=True, default=lambda self: date.today().replace(day=1) - relativedelta(months=1))
    date_to = fields.Date(required=True, default=lambda self: date.today().replace(day=1) - relativedelta(days=1))
    camp_ids = fields.Many2many('camp.camp', string='Camps', help='Leave empty for all camps in the period.')
    file_format = fields.Selection([('xlsx', 'Excel (.xlsx)'), ('csv', 'CSV')], default='xlsx', required=True)
    file_data = fields.Binary(readonly=True, attachment=False)
    file_name = fields.Char(readonly=True)

    def _columns(self):
        return [f'{g} {s}' for g, _lo, _hi in AGE_GROUPS for _k, s in SEXES]

    def _rows(self):
        """(sheet, header, rows) for patients per month and diagnoses per month."""
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_('The end date is before the start date.'))
        domain = [('state', 'not in', ('cancelled', 'booked')),
                  ('arrived_at', '>=', fields.Datetime.to_datetime(self.date_from)),
                  ('arrived_at', '<', fields.Datetime.to_datetime(self.date_to + relativedelta(days=1)))]
        if self.camp_ids:
            domain.append(('camp_id', 'in', self.camp_ids.ids))
        visits = self.env['camp.visit'].sudo().search(domain)
        cols = self._columns()

        def key(v):
            return f'{_age_group(v.patient_id.age_years)} {dict(SEXES).get(v.patient_id.sex, "M")}'

        patients = {}
        for v in visits:
            month = v.arrived_at.strftime('%Y-%m')
            row = patients.setdefault(month, dict.fromkeys(cols, 0) | {'Referred': 0})
            row[key(v)] += 1
            if v.referral_ids:
                row['Referred'] += 1
        p_rows = [[m, *[r[c] for c in cols], sum(r[c] for c in cols), r['Referred']]
                  for m, r in sorted(patients.items())]

        diagnoses = {}
        for c in self.env['camp.consultation'].sudo().search([('visit_id', 'in', visits.ids), ('state', '=', 'done')]):
            month = c.visit_id.arrived_at.strftime('%Y-%m')
            for d in c.diagnosis_ids:
                row = diagnoses.setdefault((month, d.code, d.name), dict.fromkeys(cols, 0))
                row[key(c.visit_id)] += 1
        d_rows = [[m, code, name, *[r[c] for c in cols], sum(r[c] for c in cols)]
                  for (m, code, name), r in sorted(diagnoses.items())]
        return [
            (_('Patients'), [_('Month'), *cols, _('Total'), _('Referred')], p_rows),
            (_('Diagnoses'), [_('Month'), _('ICD-10'), _('Diagnosis'), *cols, _('Total')], d_rows),
        ]

    def action_export(self):
        self.ensure_one()
        sheets = self._rows()
        stamp = f'{self.date_from:%Y%m%d}-{self.date_to:%Y%m%d}'
        if self.file_format == 'csv':
            out = io.StringIO()
            writer = csv.writer(out)
            for title, header, rows in sheets:
                writer.writerow([title])
                writer.writerow(header)
                writer.writerows(rows)
                writer.writerow([])
            data, name = out.getvalue().encode('utf-8-sig'), f'camp_health_{stamp}.csv'
        else:
            import xlsxwriter
            out = io.BytesIO()
            book = xlsxwriter.Workbook(out, {'in_memory': True})
            bold = book.add_format({'bold': True, 'bg_color': '#F4EFE7', 'border': 1})
            for title, header, rows in sheets:
                sheet = book.add_worksheet(title[:31])
                sheet.write_row(0, 0, header, bold)
                for i, row in enumerate(rows, start=1):
                    sheet.write_row(i, 0, row)
                sheet.set_column(0, 0, 10)
                sheet.set_column(1, len(header), 9)
                sheet.freeze_panes(1, 1)
            book.close()
            data, name = out.getvalue(), f'camp_health_{stamp}.xlsx'
        self.write({'file_data': base64.b64encode(data), 'file_name': name})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}
