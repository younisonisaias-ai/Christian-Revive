"""Bible College & Theology Management demo data.

Not loaded by Odoo automatically (not referenced in __manifest__.py) —
run it once by hand via `odoo shell`, e.g.:

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db \
        < /path/to/revive_bible_college/scripts/demo_data.py

Safe to re-run — it checks for the "DEMO:" name prefix first and skips
creating duplicates. Creates a tour across every part of the module:
programs, terms, courses with materials, applicants at each pipeline
stage, enrolled students with grades, assignments with a submission (one
graded, one not), Bible knowledge, a competency assessment, a sermon, a
formation record, a fieldwork placement with hours, a fee with a partial
payment, and a graduation requirement + clearance.
"""
import base64


def sample_pdf(text):
    stream = b'BT /F1 18 Tf 72 760 Td (' + text.encode('ascii') + b') Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n%s\nendstream' % (len(stream), stream),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    pdf = b'%PDF-1.4\n'
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += b'%d 0 obj\n%s\nendobj\n' % (number, body)
    xref = len(pdf)
    pdf += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    for offset in offsets:
        pdf += b'%010d 00000 n \n' % offset
    pdf += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objects) + 1, xref)
    return pdf


Program = env['college.program']
Term = env['college.term']
Course = env['college.course']
Content = env['college.course.content']
Applicant = env['college.applicant']
Student = env['college.student']
Enrollment = env['college.enrollment']
Assignment = env['college.assignment']
Submission = env['college.submission']
BibleKnowledge = env['college.bible.knowledge']
Competency = env['college.competency']
Assessment = env['college.competency.assessment']
Sermon = env['college.sermon']
Formation = env['college.formation']
Placement = env['college.placement']
PlacementLog = env['college.placement.log']
Fee = env['college.fee']
Payment = env['college.payment']
Requirement = env['college.graduation.requirement']
Clearance = env['college.graduation.clearance']

if Program.search([('name', '=', 'DEMO: Diploma in Theology')]):
    print('Demo data already exists — nothing to do. Delete records starting with "DEMO:" first if you want a clean re-run.')
else:
    program = Program.create({
        'name': 'DEMO: Diploma in Theology', 'level': 'diploma', 'duration_terms': 6,
        'description': 'A sample program for trying out the Bible College module.',
    })
    cert_program = Program.create({'name': 'DEMO: Certificate in Ministry', 'level': 'certificate', 'duration_terms': 2})

    term = Term.create({'name': 'DEMO: Spring 2026', 'start_date': '2026-01-12', 'end_date': '2026-05-15', 'state': 'active'})
    next_term = Term.create({'name': 'DEMO: Fall 2026', 'start_date': '2026-09-01', 'end_date': '2026-12-18'})

    course1 = Course.create({'name': 'DEMO: Old Testament Survey', 'code': 'OT101', 'credits': 3.0, 'program_id': program.id})
    course2 = Course.create({'name': 'DEMO: New Testament Survey', 'code': 'NT101', 'credits': 3.0, 'program_id': program.id})
    course3 = Course.create({'name': 'DEMO: Homiletics', 'code': 'HOM201', 'credits': 2.0, 'program_id': program.id})

    Content.create({
        'name': 'Course Syllabus', 'course_id': course1.id, 'content_type': 'document', 'sequence': 1,
        'attachment': base64.b64encode(sample_pdf('Old Testament Survey: sample syllabus')),
        'attachment_filename': 'ot101_syllabus.pdf',
    })
    Content.create({
        'name': 'Who Really Wrote the Bible?', 'course_id': course1.id, 'content_type': 'video', 'sequence': 2,
        'url': 'https://www.youtube.com/watch?v=Qbkj3UrkYn0',
    })
    Content.create({
        'name': 'Reading: Genesis Overview', 'course_id': course1.id, 'content_type': 'text', 'sequence': 3,
        'body': 'Genesis establishes the foundation for the entire biblical narrative: creation, fall, covenant, '
                'and the beginnings of the nation of Israel. Pay close attention to the covenant structure in '
                'chapters 12, 15 and 17.',
    })
    Content.create({
        'name': 'Recommended reading list', 'course_id': course2.id, 'content_type': 'link',
        'url': 'https://www.biblegateway.com',
    })

    # ── Applicants at every pipeline stage ──────────────────────
    draft_applicant = Applicant.create({
        'name': 'DEMO: Grace Applicant (Draft)', 'email': 'demo.grace@example.com',
        'program_id': program.id, 'term_id': next_term.id,
    })
    submitted_applicant = Applicant.create({
        'name': 'DEMO: Noah Applicant (Submitted)', 'email': 'demo.noah@example.com',
        'program_id': program.id, 'term_id': next_term.id,
    })
    submitted_applicant.action_submit()
    review_applicant = Applicant.create({
        'name': 'DEMO: Ruth Applicant (Under Review)', 'email': 'demo.ruth@example.com',
        'program_id': cert_program.id, 'term_id': next_term.id,
    })
    review_applicant.action_submit()
    review_applicant.action_under_review()
    accepted_applicant = Applicant.create({
        'name': 'DEMO: Levi Applicant (Accepted)', 'email': 'demo.levi@example.com',
        'program_id': program.id, 'term_id': next_term.id,
    })
    accepted_applicant.action_submit()
    accepted_applicant.action_under_review()
    accepted_applicant.action_accept()
    rejected_applicant = Applicant.create({
        'name': 'DEMO: Esau Applicant (Rejected)', 'email': 'demo.esau@example.com',
        'program_id': program.id, 'term_id': next_term.id,
    })
    rejected_applicant.action_submit()
    rejected_applicant.action_under_review()
    rejected_applicant.write({'decision_notes': 'Incomplete references. May reapply next term.'})
    rejected_applicant.action_reject()

    # ── Two enrolled students (one graded+published, one pending) ─
    enrolling_applicant = Applicant.create({
        'name': 'DEMO: Hannah Student', 'email': 'demo.hannah@example.com',
        'program_id': program.id, 'term_id': term.id,
    })
    enrolling_applicant.action_submit()
    enrolling_applicant.action_under_review()
    enrolling_applicant.action_accept()
    enrolling_applicant.action_enroll()
    student1 = enrolling_applicant.student_id

    enrolling_applicant2 = Applicant.create({
        'name': 'DEMO: Timothy Student', 'email': 'demo.timothy@example.com',
        'program_id': program.id, 'term_id': term.id,
    })
    enrolling_applicant2.action_submit()
    enrolling_applicant2.action_under_review()
    enrolling_applicant2.action_accept()
    enrolling_applicant2.action_enroll()
    student2 = enrolling_applicant2.student_id

    enr1 = Enrollment.create({'student_id': student1.id, 'course_id': course1.id, 'term_id': term.id})
    Enrollment.create({'student_id': student1.id, 'course_id': course2.id, 'term_id': term.id})
    enr2 = Enrollment.create({'student_id': student2.id, 'course_id': course1.id, 'term_id': term.id})

    # Publish a grade for student1/course1 so GPA shows something real.
    admin_group = env.ref('revive_bible_college.group_college_admin')
    admin = env.ref('base.user_admin')
    admin_group.write({'user_ids': [(4, admin.id)]})
    enr1_admin = enr1.with_user(admin)
    enr1.numeric_grade = 91
    enr1_admin.action_submit_grade()
    enr1_admin.action_approve_grade()
    enr1_admin.action_publish_grade()

    # Leave student2's grade mid-workflow (submitted, not published) to show "pending".
    enr2.numeric_grade = 84
    enr2.action_submit_grade()

    # ── Assignments: one graded, one awaiting grading ───────────
    assignment1 = Assignment.create({
        'name': 'DEMO: Essay — The Exodus Narrative', 'course_id': course1.id, 'term_id': term.id,
        'due_date': '2026-03-01', 'max_score': 100,
        'description': 'Write a 1500-word essay on the theological significance of the Exodus narrative.',
    })
    assignment2 = Assignment.create({
        'name': 'DEMO: Reading Reflection — Covenant Theology', 'course_id': course1.id, 'term_id': term.id,
        'due_date': '2026-02-10', 'max_score': 50,
    })
    sub1 = Submission.create({
        'assignment_id': assignment1.id, 'student_id': student1.id,
        'text_answer': 'The Exodus establishes God as a covenant-keeping deliverer...',
    })
    sub1.action_submit()
    sub1.write({'score': 95, 'feedback': 'Excellent theological depth.'})
    sub1.action_mark_graded()
    sub2 = Submission.create({
        'assignment_id': assignment2.id, 'student_id': student1.id,
        'text_answer': 'Covenant theology frames the whole canon as...',
    })
    sub2.action_submit()

    # ── Bible knowledge, competency, sermon, formation ──────────
    bk = BibleKnowledge.create({
        'student_id': student1.id, 'course_id': course1.id, 'category': 'memory',
        'passage': 'Genesis 1:1-5', 'date': '2026-02-01',
    })
    bk.action_verify()
    BibleKnowledge.create({
        'student_id': student1.id, 'category': 'quiz', 'passage': 'Pentateuch Overview Quiz',
        'score': 88, 'date': '2026-02-15',
    })

    competency = Competency.create({'name': 'DEMO: Preaching', 'description': 'Ability to prepare and deliver a sermon.'})
    Assessment.create({
        'student_id': student1.id, 'competency_id': competency.id, 'course_id': course3.id,
        'term_id': term.id, 'level': 'developing', 'date': '2026-03-10',
    })

    sermon = Sermon.create({
        'student_id': student1.id, 'course_id': course3.id, 'title': 'DEMO: Grace Abounding',
        'scripture_passage': 'Romans 5:12-21', 'sermon_date': '2026-03-15',
        'manuscript': 'Introduction: grace is not merely pardon but power...',
    })
    sermon.action_submit()
    sermon.write({'score': 88, 'feedback': 'Strong exegesis, work on pacing.'})
    sermon.action_complete_review()

    Formation.create({
        'student_id': student1.id, 'activity_type': 'mentoring', 'hours': 1.5,
        'date': '2026-02-20', 'description': 'Monthly mentoring check-in.',
    })
    Formation.create({
        'student_id': student1.id, 'activity_type': 'retreat', 'hours': 8.0,
        'date': '2026-01-18', 'description': 'Spring retreat, "Formed for Ministry".',
    })

    # ── Fieldwork placement with hours log ──────────────────────
    placement = Placement.create({
        'student_id': student1.id, 'term_id': term.id, 'site_name': 'DEMO: Grace Community Church',
        'supervisor_name': 'Pastor John Mwangi', 'supervisor_contact': '555-0100',
        'start_date': '2026-01-15', 'hours_required': 40,
    })
    placement.action_activate()
    PlacementLog.create({'placement_id': placement.id, 'date': '2026-02-01', 'hours': 10, 'activity': 'Home visitation'})
    PlacementLog.create({'placement_id': placement.id, 'date': '2026-02-15', 'hours': 12, 'activity': 'Youth ministry'})

    # ── Fee with a partial payment ───────────────────────────────
    fee = Fee.create({'student_id': student1.id, 'term_id': term.id, 'name': 'DEMO: Tuition — Spring 2026', 'amount': 1200})
    fee.action_post()
    Payment.create({'fee_id': fee.id, 'amount': 500, 'method': 'bank', 'reference': 'DEMO-TXN-001'})

    # ── Graduation requirement + clearance ──────────────────────
    Requirement.create({'name': 'DEMO: Minimum Credits Completed'})
    Requirement.create({'name': 'DEMO: Fieldwork Hours Completed'})
    clearance = Clearance.create({'student_id': student1.id, 'term_id': term.id})
    clearance.action_load_requirements()

    env.cr.commit()
    print('Demo data created:')
    print('  Programs: DEMO: Diploma in Theology, DEMO: Certificate in Ministry')
    print('  Terms: DEMO: Spring 2026 (active), DEMO: Fall 2026')
    print('  Courses: OT101, NT101, HOM201 (with sample materials)')
    print('  Applicants: one at each stage (draft/submitted/under review/accepted/rejected)')
    print('  Students: DEMO: Hannah Student (%s, published grade, GPA shows), DEMO: Timothy Student (%s, grade pending)'
          % (student1.student_code, student2.student_code))
    print('  To sign in as Hannah, choose Student, then "First time here", and use student number %s with sign-in code %s'
          % (student1.student_code, student1._new_signin_code()))
    print('  Assignments: one graded, one submitted-awaiting-grade')
    print('  Also created: Bible Knowledge, Competency Assessment, Sermon, Formation, Fieldwork Placement, Fee+Payment, Graduation Clearance')
