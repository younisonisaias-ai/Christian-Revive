{
    'name': 'Church Finance',
    'version': '1.2.0',
    'category': 'Church',
    'summary': 'Pledges, restricted funds, reconciliation and reports for Christian Revive',
    'description': """
        Christian Revive - Church Finance
        ===================================
        - Recurring/one-time pledges with progress tracking
        - Restricted funds, layered on top of Church Give's categories/projects
        - Reconciliation batches (finance officer approval workflow)
        - Expenses with approval limits, yearly budgets and fund balances
        - Reports: membership growth, giving by fund, attendance trends
        - API endpoints for the Flutter mobile app (app_get_my_pledges,
          app_create_pledge, app_get_funds, app_get_giving_by_fund, etc.)

        Builds on top of Church Give (categories/projects/transactions) and
        Church Management (RBAC scoping, pastoral/member identity) rather
        than duplicating either.
    """,
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'depends': ['base', 'church_give', 'church_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/church_give_fund_views.xml',
        'views/church_give_pledge_views.xml',
        'views/church_give_transaction_ext_views.xml',
        'views/reconciliation_views.xml',
        'views/menu.xml',
        'data/expense_data.xml',
        'views/expense_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'sequence': 17,
}
