from odoo import models

# Groups every ERP user may hold without that meaning they work in another app.
COMMON_GROUP_MODULES = ('base', 'revive_bible_college')


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _visible_menu_ids(self, debug=False):
        """College staff who have no other ERP role see only Bible College.

        This tidies their menus and opens the ERP on Bible College. It is not
        a security boundary: what they can read is set by access rights.
        """
        visible = super()._visible_menu_ids(debug)
        if not self.env.user._is_college_only():
            return visible
        root = self.env.ref('revive_bible_college.menu_bible_college_root').sudo()
        return visible & set(self.sudo().search([('id', 'child_of', root.id)]).ids)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _is_college_only(self):
        self.ensure_one()
        if not self.has_group('revive_bible_college.group_college_staff') or self.has_group('base.group_erp_manager'):
            return False
        xmlids = self.sudo().all_group_ids.get_external_id().values()
        return all(xmlid.split('.')[0] in COMMON_GROUP_MODULES for xmlid in xmlids if xmlid)
