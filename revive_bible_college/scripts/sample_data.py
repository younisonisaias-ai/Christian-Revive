"""Realistic sample data for Bible College & Theology Management.

Not loaded by Odoo automatically. Run it by hand with `odoo shell`:

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db --no-http \
        < /path/to/revive_bible_college/scripts/sample_data.py

The people and records are invented, and nothing in the ERP labels them as
samples. The script remembers exactly what it created, so
remove_sample_data.py can take it all out again. It also clears the older
records named "DEMO: ...", if any. Running it twice adds nothing the second time.
"""
import base64
import json

PARAM = 'revive_bible_college.sample_data'
# Children first: this is the order they can be deleted in.
MODELS = [
    'college.payment', 'college.fee', 'college.placement.log', 'college.placement',
    'college.submission', 'college.assignment', 'college.formation', 'college.sermon',
    'college.competency.assessment', 'college.bible.knowledge',
    'college.graduation.checklist.line', 'college.graduation.clearance',
    'college.enrollment', 'college.course.content', 'college.applicant', 'college.student',
    'college.graduation.requirement', 'college.competency', 'college.course',
    'college.term', 'college.program',
]


def sample_pdf(lines):
    text = b'BT /F1 13 Tf 72 770 Td 20 TL '
    for line in lines:
        text += b'(' + line.encode('ascii') + b') Tj T* '
    stream = text + b'ET'
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


def remove_old_demo(env):
    """Clear records from the older script, all named "DEMO: ...". All or nothing."""
    like = [('name', '=like', 'DEMO:%')]
    students = env['college.student'].search(like)
    applicants = env['college.applicant'].search(like)
    courses = env['college.course'].search(like)
    terms = env['college.term'].search(like)
    programs = env['college.program'].search(like)
    if not (students or applicants or courses or terms or programs):
        return
    try:
        with env.cr.savepoint():
            by_student = [('student_id', 'in', students.ids)]
            env['college.payment'].search([('fee_id.student_id', 'in', students.ids)]).unlink()
            env['college.fee'].search(by_student).unlink()
            env['college.placement.log'].search([('placement_id.student_id', 'in', students.ids)]).unlink()
            env['college.placement'].search(by_student).unlink()
            env['college.submission'].search(by_student).unlink()
            env['college.assignment'].search([('course_id', 'in', courses.ids)]).unlink()
            env['college.formation'].search(by_student).unlink()
            env['college.sermon'].search(by_student).unlink()
            env['college.competency.assessment'].search(by_student).unlink()
            env['college.bible.knowledge'].search(by_student).unlink()
            env['college.graduation.clearance'].search(by_student).unlink()
            env['college.enrollment'].search(by_student).unlink()
            applicants.write({'student_id': False})
            students.write({'applicant_id': False})
            applicants.unlink()
            students.unlink()
            env['college.graduation.requirement'].search(like).unlink()
            env['college.competency'].search(like).unlink()
            courses.unlink()
            terms.unlink()
            programs.unlink()
        print('Removed the older "DEMO:" records (%d students, %d applicants, %d courses).'
              % (len(students), len(applicants), len(courses)))
    except Exception as error:
        print('Could not remove the older "DEMO:" records, so they were left as they were: %s' % error)


admin = env.ref('base.user_admin')
env = env(user=admin.id, su=True)
Params = env['ir.config_parameter']

if Params.get_param(PARAM):
    print('The sample data is already there. Nothing was added.')
else:
    remove_old_demo(env)
    # An empty recordset's .id is False, not 0 — coerce so the ">" comparison below stays an integer one.
    before = {m: (env[m].search([], order='id desc', limit=1).id or 0) for m in MODELS}

    def find_or_create(model, vals):
        return env[model].search([('name', '=', vals['name'])], limit=1) or env[model].create(vals)

    # ── Programs, terms, courses (anything already there is reused) ──
    diploma = find_or_create('college.program', {
        'name': 'Diploma in Theology', 'code': 'DTH', 'level': 'diploma', 'duration_terms': 4,
        'description': 'Two years of Bible, doctrine and practical ministry.'})
    certificate = find_or_create('college.program', {
        'name': 'Certificate in Biblical Studies', 'code': 'CBS', 'level': 'certificate', 'duration_terms': 2})
    bachelor = find_or_create('college.program', {
        'name': 'Bachelor of Divinity', 'code': 'BD', 'level': 'bachelor', 'duration_terms': 8})

    fall = find_or_create('college.term', {
        'name': 'Fall 2026', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
    spring = find_or_create('college.term', {
        'name': 'Spring 2027', 'start_date': '2027-01-11', 'end_date': '2027-05-14'})

    def course(name, code, credits_):
        return find_or_create('college.course', {'name': name, 'code': code, 'credits': credits_, 'program_id': diploma.id})

    ot = course('Old Testament Survey', 'OT101', 3)
    nt = course('New Testament Survey', 'NT101', 3)
    homiletics = course('Homiletics', 'HOM201', 2)
    theology = course('Systematic Theology', 'TH201', 3)
    history = course('Church History', 'CH101', 2)
    pastoral = course('Pastoral Care', 'PC210', 2)

    Content = env['college.course.content']
    Content.create({
        'name': 'Course syllabus', 'course_id': ot.id, 'content_type': 'document', 'sequence': 1,
        'attachment': base64.b64encode(sample_pdf([
            'Old Testament Survey (OT101) - Fall 2026',
            '',
            'This course walks through the Old Testament from Genesis to Malachi.',
            'Weeks 1-4: The Pentateuch',
            'Weeks 5-8: The historical books',
            'Weeks 9-11: Wisdom and poetry',
            'Weeks 12-15: The prophets',
            '',
            'Marks: essay 40%, reflection 20%, book review 20%, final exam 20%.',
        ])),
        'attachment_filename': 'ot101_syllabus.pdf',
    })
    Content.create({
        'name': 'Who Really Wrote the Bible?', 'course_id': ot.id, 'content_type': 'video', 'sequence': 2,
        'url': 'https://www.youtube.com/watch?v=Qbkj3UrkYn0'})
    Content.create({
        'name': 'Reading: Genesis overview', 'course_id': ot.id, 'content_type': 'text', 'sequence': 3,
        'body': 'Genesis lays the foundation for the whole Bible: creation, fall, covenant and the beginnings '
                'of Israel. Pay close attention to the covenant in chapters 12, 15 and 17.'})
    Content.create({
        'name': 'Parallel Bible reader', 'course_id': ot.id, 'content_type': 'link', 'sequence': 4,
        'url': 'https://www.biblegateway.com'})

    # ── Applicants at every stage, and the students who came through ──
    def applicant(name, program, term, phone, stop, notes=None):
        record = env['college.applicant'].create({
            'name': name, 'email': '%s@example.com' % name.lower().replace(' ', '.'), 'phone': phone,
            'program_id': program.id, 'term_id': term.id})
        steps = {
            'draft': [], 'submitted': ['action_submit'],
            'under_review': ['action_submit', 'action_under_review'],
            'accepted': ['action_submit', 'action_under_review', 'action_accept'],
            'rejected': ['action_submit', 'action_under_review', 'action_reject'],
            'enrolled': ['action_submit', 'action_under_review', 'action_accept', 'action_enroll'],
        }[stop]
        if notes:
            record.decision_notes = notes
        for step in steps:
            getattr(record, step)()
        return record

    names = ['Sarah Masih', 'Daniel Gill', 'Naomi Bhatti', 'Joshua Sadiq', 'Esther Yousaf', 'Samuel Javed', 'Miriam Shahzad', 'Peter Nazir']
    students = [
        applicant(n, certificate if n == 'Peter Nazir' else diploma, fall, '0300-555-01%02d' % i, 'enrolled').student_id
        for i, n in enumerate(names)
    ]
    sarah, daniel, naomi, joshua, esther, samuel = students[:6]

    applicant('Hannah Pervaiz', diploma, spring, '0300-555-0121', 'submitted')
    applicant('Timothy Akram', bachelor, spring, '0300-555-0122', 'submitted')
    applicant('Ruth Emmanuel', certificate, spring, '0300-555-0123', 'under_review',
              notes='We will call you this week for a short interview.')
    applicant('Caleb Anwar', diploma, spring, '0300-555-0124', 'under_review')
    applicant('Lydia Rafiq', diploma, spring, '0300-555-0125', 'accepted', notes='References checked. Welcome to the college.')
    applicant('Andrew Iqbal', bachelor, spring, '0300-555-0126', 'accepted')
    applicant('Martha Saleem', certificate, spring, '0300-555-0127', 'draft')
    applicant('Philip Arif', bachelor, spring, '0300-555-0128', 'rejected', notes='References incomplete. Welcome to reapply next term.')

    # ── Courses and grades, at every approval stage ──
    def enroll(student, enrolled_course, score=None, stop='published'):
        record = env['college.enrollment'].create({'student_id': student.id, 'course_id': enrolled_course.id, 'term_id': fall.id})
        if score is not None:
            record.numeric_grade = score
            record._do_submit_grade(admin)
            if stop in ('approved', 'published'):
                record._do_approve_grade(admin)
            if stop == 'published':
                record._do_publish_grade()
        return record

    enroll(sarah, ot, 92)
    enroll(sarah, nt, 86)
    enroll(sarah, homiletics, 78, 'submitted')
    enroll(daniel, ot, 81)
    enroll(daniel, nt, 88, 'approved')
    enroll(daniel, homiletics)
    enroll(naomi, ot, 95)
    enroll(naomi, theology, 90)
    enroll(naomi, homiletics)
    enroll(joshua, ot, 73)
    enroll(joshua, history, 84, 'submitted')
    enroll(esther, nt)
    enroll(samuel, pastoral)

    # ── Assignments ──
    Assignment = env['college.assignment']
    essay = Assignment.create({
        'name': 'Essay: The Exodus Narrative', 'course_id': ot.id, 'term_id': fall.id, 'due_date': '2026-10-15', 'max_score': 100,
        'description': 'Write 1,500 words on the theological meaning of the Exodus.'})
    Assignment.create({
        'name': 'Reflection: Covenant in Genesis', 'course_id': ot.id, 'term_id': fall.id, 'due_date': '2026-11-20', 'max_score': 50,
        'description': 'Write one page on how the covenant with Abraham shapes the rest of Genesis.'})
    Assignment.create({
        'name': 'Book review: The Prophets', 'course_id': ot.id, 'term_id': fall.id, 'due_date': '2026-12-05', 'max_score': 100,
        'description': 'Review a book of your choice on the Old Testament prophets.'})
    Assignment.create({
        'name': 'Exegesis: Romans 8', 'course_id': nt.id, 'term_id': fall.id, 'due_date': '2026-11-28', 'max_score': 100,
        'description': 'Work through Romans 8:1-17 verse by verse.'})
    graded = env['college.submission'].create({
        'assignment_id': essay.id, 'student_id': sarah.id,
        'text_answer': 'The Exodus shows God as a deliverer who keeps covenant with his people.'})
    graded.action_submit()
    graded.write({'score': 94, 'feedback': 'Clear argument and good use of Scripture.'})
    graded.action_mark_graded()
    env['college.submission'].create({
        'assignment_id': essay.id, 'student_id': daniel.id,
        'text_answer': 'Israel learns who God is by being rescued.'}).action_submit()

    # ── Bible knowledge and competency ──
    Knowledge = env['college.bible.knowledge']
    Knowledge.create({'student_id': sarah.id, 'course_id': ot.id, 'category': 'memory', 'passage': 'Psalm 23', 'date': '2026-09-20'}).action_verify()
    Knowledge.create({'student_id': daniel.id, 'course_id': ot.id, 'category': 'memory', 'passage': 'Isaiah 53:1-6', 'date': '2026-09-27'}).action_verify()
    Knowledge.create({'student_id': sarah.id, 'course_id': ot.id, 'category': 'quiz', 'passage': 'Pentateuch overview', 'score': 88, 'date': '2026-10-04'})
    Knowledge.create({'student_id': naomi.id, 'course_id': nt.id, 'category': 'reading', 'passage': 'Gospel of John', 'score': 100, 'date': '2026-10-11'})
    Knowledge.create({'student_id': joshua.id, 'category': 'memory', 'passage': 'Romans 12:1-2', 'date': '2026-10-18'})

    preaching = find_or_create('college.competency', {'name': 'Preaching', 'description': 'Prepares and delivers a faithful sermon.'})
    care = find_or_create('college.competency', {'name': 'Pastoral Care', 'description': 'Visits, listens and prays with people.'})
    exegesis = find_or_create('college.competency', {'name': 'Biblical Exegesis', 'description': 'Reads a passage carefully in its context.'})
    for student, competency, level, date in [
        (sarah, preaching, 'developing', '2026-09-25'), (sarah, preaching, 'proficient', '2026-10-25'),
        (sarah, exegesis, 'proficient', '2026-10-10'), (daniel, care, 'developing', '2026-10-12'),
        (naomi, exegesis, 'advanced', '2026-10-14'), (joshua, preaching, 'novice', '2026-10-16'),
    ]:
        env['college.competency.assessment'].create({
            'student_id': student.id, 'competency_id': competency.id, 'term_id': fall.id, 'level': level, 'date': date})

    # ── Sermons and spiritual formation ──
    Sermon = env['college.sermon']
    sermon = Sermon.create({
        'student_id': sarah.id, 'course_id': homiletics.id, 'title': 'Grace Abounding', 'scripture_passage': 'Romans 5:12-21',
        'sermon_date': '2026-10-18', 'manuscript': 'Where sin increased, grace abounded all the more. Three things this passage teaches about grace.'})
    sermon.action_submit()
    sermon.write({'score': 88, 'feedback': 'Strong exegesis. Slow down in the application.'})
    sermon.action_complete_review()
    Sermon.create({
        'student_id': daniel.id, 'course_id': homiletics.id, 'title': 'The Good Shepherd',
        'scripture_passage': 'John 10:1-18', 'sermon_date': '2026-10-25'}).action_submit()
    Sermon.create({
        'student_id': naomi.id, 'course_id': homiletics.id, 'title': 'Faith That Works',
        'scripture_passage': 'James 2:14-26', 'sermon_date': '2026-11-08'})

    for student, kind, hours, date, text, verified in [
        (sarah, 'mentoring', 1.5, '2026-09-22', 'Monthly mentoring meeting.', True),
        (sarah, 'retreat', 8, '2026-10-03', 'Fall retreat.', True),
        (daniel, 'service', 4, '2026-10-10', 'Food distribution with the local church.', True),
        (naomi, 'devotional', 1, '2026-10-12', 'Daily prayer journal.', False),
        (joshua, 'mentoring', 1, '2026-10-20', 'First mentoring meeting.', False),
    ]:
        env['college.formation'].create({
            'student_id': student.id, 'activity_type': kind, 'hours': hours, 'date': date, 'description': text, 'verified': verified})

    # ── Fieldwork ──
    Placement = env['college.placement']
    Log = env['college.placement.log']
    placement = Placement.create({
        'student_id': sarah.id, 'term_id': fall.id, 'site_name': "St. Peter's Church", 'site_address': 'Main Road, Lahore',
        'supervisor_name': 'Rev. John Mathews', 'supervisor_contact': '0300-555-0190',
        'start_date': '2026-09-07', 'end_date': '2026-12-11', 'hours_required': 40})
    placement.action_activate()
    for date, hours, activity in [
        ('2026-09-13', 4, 'Sunday school teaching'), ('2026-09-27', 6, 'Home visitation'),
        ('2026-10-11', 5, 'Youth meeting'), ('2026-10-25', 7, 'Assisted in Sunday worship'),
    ]:
        Log.create({'placement_id': placement.id, 'date': date, 'hours': hours, 'activity': activity})
    finished = Placement.create({
        'student_id': daniel.id, 'term_id': fall.id, 'site_name': 'Grace Community Church',
        'supervisor_name': 'Pastor Imran Paul', 'hours_required': 40, 'start_date': '2026-09-07'})
    finished.action_activate()
    Log.create({'placement_id': finished.id, 'date': '2026-10-04', 'hours': 40, 'activity': 'Hospital visitation and outreach'})
    finished.action_complete()
    finished.action_verify()

    # ── Fees ──
    Fee = env['college.fee']
    Payment = env['college.payment']
    for number, (student, payments) in enumerate([
        (sarah, [(20000, 'bank', '2026-09-10'), (10000, 'cash', '2026-10-10')]),
        (daniel, [(45000, 'bank', '2026-09-12')]),
        (naomi, []),
        (joshua, [(15000, 'cash', '2026-09-20')]),
    ]):
        fee = Fee.create({'student_id': student.id, 'term_id': fall.id, 'name': 'Tuition, Fall 2026', 'amount': 45000, 'due_date': '2026-09-15'})
        fee.action_post()
        for index, (amount, method, date) in enumerate(payments):
            Payment.create({'fee_id': fee.id, 'amount': amount, 'method': method, 'date': date,
                            'reference': 'RCPT-%d' % (1041 + number * 10 + index)})

    # ── Graduation ──
    for sequence, name in enumerate(['Required credits completed', 'All fees paid', 'Fieldwork hours verified',
                                     'Final sermon reviewed', 'Spiritual formation record complete']):
        find_or_create('college.graduation.requirement', {'name': name, 'sequence': sequence})
    clearance = env['college.graduation.clearance'].create({'student_id': naomi.id, 'term_id': fall.id})
    clearance.action_load_requirements()
    clearance.checklist_ids[:3].write({'done': True})

    # ── Sign-in codes to try the student login with ──
    sarah_code = sarah._new_signin_code()
    daniel_code = daniel._new_signin_code()

    created = {m: env[m].search([('id', '>', before[m])]).ids for m in MODELS}
    Params.set_param(PARAM, json.dumps(created))
    env.cr.commit()

    print('Sample data added: %d students, %d applicants, %d courses.' % (
        len(created['college.student']), len(created['college.applicant']), len(created['college.course'])))
    print('Try the student login. Choose Student, then "First time here, or forgot your password?":')
    print('  Sarah Masih: student number %s, sign-in code %s' % (sarah.student_code, sarah_code))
    print('  Daniel Gill: student number %s, sign-in code %s' % (daniel.student_code, daniel_code))
    print('Each code works once, for 7 days.')
