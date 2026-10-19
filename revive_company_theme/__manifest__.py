{
    'name': 'Company App Theme',
    'version': '1.0.0',
    'category': 'Hidden',
    'summary': 'Colour the backend by the company you are working in',
    'description': """
        Each company can have its own backend colours (Settings → Companies →
        App Theme). When you switch company, buttons, links, checkboxes, tabs
        and search tags take that company's colours. A company with no colours
        set keeps the default look (for Revive Lifestyle, its sage green).
        Christian Revive is set to the app's brown on install.
    """,
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'depends': ['base', 'web'],
    'data': [
        'views/res_company_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'revive_company_theme/static/src/company_theme.scss',
            'revive_company_theme/static/src/company_theme.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'license': 'LGPL-3',
}
