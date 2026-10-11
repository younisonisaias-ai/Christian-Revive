"""Tests the doctor orders during the visit (sugar, haemoglobin, malaria…),
done at the camp's lab desk; the result goes back to the doctor."""
from odoo import api, fields, models

LAB_TESTS = [
    ('blood_sugar', 'Blood sugar (mg/dL)'),
    ('hemoglobin', 'Haemoglobin (g/dL)'),
    ('malaria', 'Malaria rapid test'),
    ('urine', 'Urine dipstick'),
    ('pregnancy', 'Pregnancy test'),
    ('typhoid', 'Typhoid rapid test'),
    ('hepatitis_b', 'Hepatitis B rapid test'),
    ('hepatitis_c', 'Hepatitis C rapid test'),
    ('other', 'Other'),
]


class CampLabOrder(models.Model):
    _name = 'camp.lab.order'
    _description = 'Camp Lab Test'
    _inherit = ['camp.sync.mixin']
    _order = 'id desc'

    visit_id = fields.Many2one('camp.visit', required=True, ondelete='cascade', index=True)
    camp_id = fields.Many2one(related='visit_id.camp_id', store=True, index=True)
    patient_id = fields.Many2one(related='visit_id.patient_id', store=True)
    test = fields.Selection(LAB_TESTS, required=True)
    test_name = fields.Char(help='For "Other": which test.')
    state = fields.Selection([('ordered', 'Waiting at lab'), ('done', 'Result ready'), ('cancelled', 'Cancelled')],
                             default='ordered', required=True, index=True)
    result = fields.Char()
    abnormal = fields.Boolean(help='Outside the normal range, or a positive rapid test.')
    notes = fields.Char()
    ordered_by_id = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True)
    ordered_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    done_by_id = fields.Many2one('res.users', readonly=True)
    done_at = fields.Datetime(readonly=True)

    @api.depends('test', 'test_name', 'result')
    def _compute_display_name(self):
        labels = dict(LAB_TESTS)
        for o in self:
            name = o.test_name if o.test == 'other' and o.test_name else labels.get(o.test, '')
            o.display_name = f'{name}: {o.result}' if o.result else name

    def write(self, vals):
        res = super().write(vals)
        # A positive pregnancy test marks the visit, so medicines are checked.
        if vals.get('result') or vals.get('state') == 'done':
            for o in self.filtered(lambda o: o.test == 'pregnancy' and o.state == 'done'):
                if (o.result or '').strip().lower() in ('positive', 'pos', '+', 'مثبت'):
                    o.visit_id.sudo().pregnant = True
        return res
