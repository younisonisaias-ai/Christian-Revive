{
    'name': 'Medical Camp - Volunteers',
    'version': '19.0.1.0.0',
    'category': 'Healthcare',
    'summary': 'Pick camp team members from the volunteer list',
    'description': """
Links Medical Camp team members to volunteers (contacts marked as volunteers).
Installs automatically when both Medical Camp Management and the volunteer module are present.
""",
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'license': 'LGPL-3',
    'depends': ['revive_medical_camp', 'volunteer_and_donation_management'],
    'data': ['views/camp_camp_views.xml'],
    'auto_install': True,
    'installable': True,
}
