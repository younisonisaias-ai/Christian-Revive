from odoo import models, fields


class HrEmployeeCollege(models.Model):
    _inherit = 'hr.employee'

    # Reuses the shared staff_role field (base defined in
    # volunteer_and_donation_management) so Bible College staff sign into
    # the app the same way every other staff role already does.
    staff_role = fields.Selection(selection_add=[
        ('college_staff', 'Bible College Staff'),
        ('college_admin', 'Bible College Admin'),
    ], ondelete={
        'college_staff': lambda recs: recs.write({'staff_role': False}),
        'college_admin': lambda recs: recs.write({'staff_role': False}),
    })
