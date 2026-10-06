{
    'name': 'Church Management',
    'version': '1.11.0',
    'category': 'Church',
    'summary': 'Membership CRM, cell groups, pastoral care, attendance and admin dashboard for Christian Revive',
    'description': """
        Christian Revive - Church Management
        =====================================
        - Interactive Admin Dashboard with real-time analytics, KPI cards, attendance trends, care alerts, and absenteeism watchlist
        - Membership lifecycle (visitor -> member -> leader), families/households
        - Member profile: member number, personal details, gifts & ministry,
          emergency contact, baptism place, transfers, profile completeness
        - Pastor-to-member assignment and senior pastor scope
        - Cell / small groups with leader and roster
        - Pastoral care notes (restricted to author + senior pastor/admin),
          visits, follow-ups with outcomes, member care status
        - Prayer request care: privacy levels, workflow, pastor assignment
        - Church services & events (Sabbath worship, Sabbath School, prayer
          meeting, youth, ...) with check-in / attendance tracking
        - API endpoints for the Flutter mobile app (app_get_members,
          app_get_cell_groups, app_check_in, app_get_pastoral_notes, etc.)
    """,
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'depends': ['base', 'contacts', 'hr', 'volunteer_and_donation_management'],
    'data': [
        'security/ir.model.access.csv',
        'security/church_management_security.xml',
        'data/member_sequence.xml',
        'data/cron.xml',
        'views/church_dashboard_views.xml',
        'views/church_member_views.xml',
        'views/hr_employee_pastor_views.xml',
        'views/cell_group_views.xml',
        'views/pastoral_care_note_views.xml',
        'views/prayer_care_views.xml',
        'views/church_service_views.xml',
        'views/event_attendance_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'church_management/static/src/dashboard/church_dashboard.js',
            'church_management/static/src/dashboard/church_dashboard.xml',
            'church_management/static/src/dashboard/church_dashboard.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'sequence': 16,
}

