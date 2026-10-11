"""Stock planning for a coming camp: how much of each medicine to take, from
what earlier camps used per patient, and what is expiring."""
import math
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

PAST_CAMPS = 5       # learn from the last 5 closed camps
BUFFER = 1.2         # take 20% more than expected
EXPIRY_DAYS = 60     # warn about lots expiring within 60 days after the camp


def _main_stock(camp):
    warehouse = camp.env['stock.warehouse'].sudo().search([('company_id', '=', camp.company_id.id)], limit=1)
    if not warehouse:
        raise UserError(_('No warehouse found for %s.', camp.company_id.name))
    return warehouse


def _qty(env, product, location):
    quants = env['stock.quant'].sudo().search([('product_id', '=', product.id), ('location_id', 'child_of', location.id)])
    return sum(quants.mapped('quantity')) - sum(quants.mapped('reserved_quantity'))


class CampStockPlan(models.TransientModel):
    _name = 'camp.stock.plan'
    _description = 'Camp stock plan'

    camp_id = fields.Many2one('camp.camp', required=True)
    expected_patients = fields.Integer(required=True)
    line_ids = fields.One2many('camp.stock.plan.line', 'plan_id')
    based_on = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        camp = self.env['camp.camp'].browse(self.env.context.get('active_id'))
        if camp:
            res['camp_id'] = camp.id
            res['expected_patients'] = camp.expected_patients or 300
        return res

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        for plan in plans:
            plan._fill()
        return plans

    def action_recalculate(self):
        self._fill()
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}

    def _fill(self):
        self.ensure_one()
        camp = self.camp_id
        past = self.env['camp.camp'].sudo().search(
            [('state', '=', 'closed'), ('id', '!=', camp.id)], order='date_start desc', limit=PAST_CAMPS)
        patients = sum(len(c.visit_ids.filtered(lambda v: v.state not in ('cancelled', 'booked'))) for c in past)
        lines = self.env['camp.prescription.line'].sudo().search([('camp_id', 'in', past.ids), ('dispensed_qty', '>', 0)])
        used = {}
        for line in lines:
            med = line.substitute_formulary_id or line.formulary_id
            used[med] = used.get(med, 0) + line.dispensed_qty
        main = _main_stock(camp).lot_stock_id
        soon = (camp.date_start or fields.Date.today()) + timedelta(days=EXPIRY_DAYS)
        rows = []
        for f in self.env['camp.formulary'].sudo().search([]):
            per_100 = (used.get(f, 0) / patients * 100) if patients else 0
            suggested = math.ceil(per_100 * self.expected_patients / 100 * BUFFER)
            at_camp = _qty(self.env, f.product_id, camp.stock_location_id) if camp.stock_location_id else 0
            expiring = self.env['stock.quant'].sudo().search([
                ('product_id', '=', f.product_id.id), ('location_id', 'child_of', main.id), ('quantity', '>', 0),
                ('lot_id.expiration_date', '!=', False), ('lot_id.expiration_date', '<=', fields.Datetime.to_datetime(soon))])
            rows.append((0, 0, {
                'formulary_id': f.id, 'per_100': round(per_100, 1), 'suggested': suggested, 'at_camp': at_camp,
                'at_main': _qty(self.env, f.product_id, main), 'to_send': max(0, suggested - at_camp),
                'expiring_qty': sum(expiring.mapped('quantity')),
            }))
        self.line_ids = [(5, 0, 0)] + rows
        self.based_on = _('%(camps)s earlier camps, %(patients)s patients', camps=len(past), patients=patients) \
            if past else _('No earlier camps yet: enter the amounts yourself.')

    def action_create_transfer(self):
        """A draft transfer from the main store to the camp, for the stock team to check and validate."""
        self.ensure_one()
        camp = self.camp_id
        if not camp.stock_location_id:
            raise UserError(_('This camp has no stock location.'))
        warehouse = _main_stock(camp)
        lines = self.line_ids.filtered(lambda l: l.to_send > 0)
        if not lines:
            raise UserError(_('Nothing to send.'))
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': warehouse.lot_stock_id.id,
            'location_dest_id': camp.stock_location_id.id,
            'origin': camp.name,
            'move_ids': [(0, 0, {
                'product_id': l.formulary_id.product_id.id, 'product_uom_qty': l.to_send,
                'product_uom': l.formulary_id.product_id.uom_id.id,
                'location_id': warehouse.lot_stock_id.id, 'location_dest_id': camp.stock_location_id.id,
            }) for l in lines],
        })
        return {'type': 'ir.actions.act_window', 'res_model': 'stock.picking', 'res_id': picking.id,
                'view_mode': 'form', 'target': 'current'}


class CampStockPlanLine(models.TransientModel):
    _name = 'camp.stock.plan.line'
    _description = 'Camp stock plan line'

    plan_id = fields.Many2one('camp.stock.plan', required=True, ondelete='cascade')
    formulary_id = fields.Many2one('camp.formulary', string='Medicine', readonly=True)
    per_100 = fields.Float(string='Used per 100 patients', readonly=True)
    suggested = fields.Float(string='Suggested', readonly=True)
    at_camp = fields.Float(string='Already at camp', readonly=True)
    at_main = fields.Float(string='In main store', readonly=True)
    to_send = fields.Float(string='To send')
    expiring_qty = fields.Float(string='Expiring soon (main store)', readonly=True)
