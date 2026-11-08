{
    'name': 'Bible College & Theology Management',
    'version': '19.0.1.14.0',
    'category': 'Education',
    'summary': 'Admissions, academics, gradebook, LMS, formation, fieldwork, fees, graduation and app access for a Bible college',
    # Phase 9 adds public, no-login endpoints: app_college_public_apply,
    # app_college_check_application, app_college_public_lookups and
    # app_college_student_lookup. Grades are hidden from students until
    # their enrollment's grade_state is 'published' (see _app_self_detail).
    # Also: app_college_student_content (download, scoped to enrolled
    # courses only), app_college_student_assignments/submit_assignment
    # (scoped to enrolled course+term pairs only).
    'description': """
Bible College & Theology Management
====================================
A standalone module for running a Bible college or seminary, start to finish:

* Programs, academic terms and courses
* Applicant intake and admission decisions
* Student records and course enrollment
* Gradebook: draft -> submitted -> approved -> published grading,
  GPA and completed credits per student
* Course materials (documents, videos, links, text, quizzes), assignments
  and student submissions (draft -> submitted -> graded)
* Multiple-choice quizzes with instant scoring and a per-question
  explanation; passing a quiz marks its lesson complete, same as
  finishing a video
* Flashcard decks for memory work (a verse, a term, an event); a
  student marks each card known or still learning, and finishing a
  deck marks its lesson complete too
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
  Christian Revive app itself, through their own College Staff and College
  Admin sign-ins. Staff submit grades; admins approve and publish them.
* Students sign in with their student number and a password, in the app or
  at /college in a browser. A one-time code from the college office sets the
  password. Grades only ever show once staff has published them.
* Anyone can apply from the app with no account needed, and check their
  application afterwards using their application number plus their email.
* College staff with no other ERP role see only Bible College in the ERP.

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
        'data/college_cron.xml',
        'views/college_program_views.xml',
        'views/college_term_views.xml',
        'views/college_course_views.xml',
        'views/college_course_module_views.xml',
        'views/college_quiz_views.xml',
        'views/college_flashcard_views.xml',
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
        'views/college_portal_templates.xml',
        'views/college_menus.xml',
    ],
    'installable': True,
    'application': True,
}
