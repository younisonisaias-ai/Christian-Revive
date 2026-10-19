from . import models

# The app's brown, from the Flutter app's "Brown" palette.
CHRISTIAN_REVIVE_PRIMARY = '#4A3728'
CHRISTIAN_REVIVE_SECONDARY = '#8B6B4A'


def post_init_hook(env):
    """Give the Christian Revive company the app's brown."""
    companies = env['res.company'].search([('name', 'ilike', 'christian revive')])
    companies.write({
        'app_theme_primary': CHRISTIAN_REVIVE_PRIMARY,
        'app_theme_secondary': CHRISTIAN_REVIVE_SECONDARY,
    })
