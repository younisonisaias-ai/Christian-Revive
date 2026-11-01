{
    'name': 'Bible College & Theology Management',
    'version': '19.0.1.8.0',
    'category': 'Education',
    'summary': 'Admissions, academics, gradebook, LMS, formation, fieldwork, fees, graduation and app access for a Bible college',
    # Phase 9 adds public, no-login endpoints: app_college_public_apply,
    # app_college_check_application, app_college_public_lookups and
    # app_college_student_lookup. Grades are hidden from students until
    # their enrollment's grade_state is 'published' (see _app_self_detail).
    'description': """
Bible College & Theology Management
====================================
A standalone module for running a Bible college or seminary, start to finish:

* Programs, academic terms and courses
* Applicant intake and admission decisions
* Student records and course enrollment
* Gradebook: draft -> submitted -> approved -> published grading,
  GPA and completed credits per student
* Course materials (documents, videos, links, text), assignments and
  student submissions (draft -> submitted -> graded)
* Bible knowledge / scripture memory tracking, and ministry competency
  assessments (Novice -> Developing -> Proficient -> Advanced)
* Sermon submission and review (draft -> submitted -> reviewed), and
  spiritual formation activity tracking
* Fieldwork / ministry placements with an hours log and supervisor
  verification (draft -> active -> completed -> verified)
* Fees / tuition charges with payments and balance tracking (kept as
  its own simple ledger, not tied to Odoo's accounting app)
* Graduation requirements checklist and clearance (draft -> cleared ->
  graduated), which also marks the student record as graduated
* Staff can manage applicants, students and course enrollment from the
  Christian Revive app itself (adds Bible College Staff / Bible College
  Admin as app staff roles, reusing the app's existing sign-in)
* Anyone can apply from the app with no account needed, and check their
  application or (once enrolled) their enrollment/grades/course content
  afterwards using their application/student number plus their email.
  Grades only ever show once staff has published them.

Core record-keeping stays independent of Church Management so it could
move to its own database later; the app sign-in integration (above) is
the one part that depends on Church Management's session system.
""",
    'author': 'Christian Revive',
    'website': 'https://christianrevive.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'church_management'],
    'data': [
        'security/college_security.xml',
        'security/ir.model.access.csv',
        'data/college_sequence.xml',
        'views/college_program_views.xml',
        'views/college_term_views.xml',
        'views/college_course_views.xml',
        'views/college_applicant_views.xml',
        'views/college_enrollment_views.xml',
        'views/college_assignment_views.xml',
        'views/college_submission_views.xml',
        'views/college_bible_knowledge_views.xml',
        'views/college_competency_views.xml',
        'views/college_sermon_views.xml',
        'views/college_formation_views.xml',
        'views/college_placement_views.xml',
        'views/college_fee_views.xml',
        'views/college_graduation_views.xml',
        'views/college_student_views.xml',
        'views/college_menus.xml',
    ],
    'installable': True,
    'application': True,
}
