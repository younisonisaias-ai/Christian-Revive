import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _darker(hex_color, amount=0.18):
    r, g, b = (round(c * (1 - amount)) for c in _rgb(hex_color))
    return f'#{r:02x}{g:02x}{b:02x}'


class ResCompany(models.Model):
    _inherit = 'res.company'

    app_theme_primary = fields.Char(
        string='Main colour',
        help='Buttons, links, checkboxes and active tabs for this company. '
             'Leave empty to keep the default look.')
    app_theme_secondary = fields.Char(
        string='Highlight colour', help='Search tags and highlights. Defaults to the main colour.')

    @api.constrains('app_theme_primary', 'app_theme_secondary')
    def _check_theme_colours(self):
        for company in self:
            for value in (company.app_theme_primary, company.app_theme_secondary):
                if value and not HEX.match(value):
                    raise ValidationError('Colours must look like #4A3728.')

    def _app_theme(self):
        self.ensure_one()
        primary = self.app_theme_primary
        if not primary or not HEX.match(primary):
            return None
        secondary = self.app_theme_secondary if self.app_theme_secondary and \
            HEX.match(self.app_theme_secondary) else primary
        return {
            'primary': primary,
            'primary_dark': _darker(primary),
            'primary_rgb': ', '.join(str(c) for c in _rgb(primary)),
            'secondary': secondary,
        }


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Send each allowed company's theme colours to the web client."""
        result = super().session_info()
        user = self.env.user
        if user and not user._is_public():
            colours = {}
            for company in user.sudo().company_ids:
                theme = company._app_theme()
                if theme:
                    colours[company.id] = theme
            result['revive_company_themes'] = colours
        return result
