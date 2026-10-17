"""Removable sample data for testing Church Management on a live database.

Every record this script creates is registered under the external-id module
``__church_sample__`` and its name carries "(Sample)", so ``remove`` deletes
exactly these records and nothing else.

Run from the compose folder on the server (it reads this file on stdin):

  Load:   docker compose exec -T -e SAMPLE_ACTION=load   service_revive_odoo19 \
              odoo shell -d revive_db --no-http < Christian-Revive/tools/church_sample_data.py
  Remove: docker compose exec -T -e SAMPLE_ACTION=remove service_revive_odoo19 \
              odoo shell -d revive_db --no-http < Christian-Revive/tools/church_sample_data.py

Safety:
- No push notifications: prayer requests are "prayer team" visibility and not
  urgent (urgent/private requests alert real pastors); no pledge reminder dates.
- Nothing appears to app users on the public prayer wall or the Give page: no
  sample funds or public prayers are created.
- Sample members get "SAMPLE-xx" numbers, so the real member-number sequence is
  not used up.
- Sample people only belong to sample cell groups, so inactivity alerts never
  reach a real group leader.
"""
import os
from datetime import date, datetime, time, timedelta

MODULE = '__church_sample__'
TEST_PASTOR_EMAIL = 'pastor.test@christianrevive.com'
TEST_FINANCE_EMAIL = 'finance.test@christianrevive.com'
# Delete children before parents.
REMOVE_ORDER = [
    'church.expense.log', 'church.expense', 'church.budget.line', 'church.budget',
    'church.event.attendance', 'pastoral.care.note', 'prayer.request',
    'church.give.transaction', 'church.give.pledge', 'pastor.assignment',
    'cell.group', 'church.service', 'church.family', 'res.partner',
]

Data = env['ir.model.data'].sudo()  # noqa: F821 (provided by odoo shell)
today = date.today()
counter = {}


def track(record):
    for rec in record:
        Data.create({'module': MODULE, 'name': '%s_%s' % (rec._name.replace('.', '_'), rec.id),
                     'model': rec._name, 'res_id': rec.id, 'noupdate': True})
        counter[rec._name] = counter.get(rec._name, 0) + 1
    return record


def make(model, vals):
    return track(env[model].sudo().create(vals))  # noqa: F821


def has(model, *fields):
    return model in env and all(f in env[model]._fields for f in fields)  # noqa: F821


def utc(day, hour_pkt):
    """Pakistan time (UTC+5) to the naive UTC datetimes Odoo stores."""
    return datetime.combine(day, time(hour_pkt)) - timedelta(hours=5)


def staff_by_email(email):
    Employee = env['hr.employee'].sudo()  # noqa: F821
    return Employee.search([('app_email', '=ilike', email)], limit=1)


def load():
    if Data.search_count([('module', '=', MODULE)]):
        print('Sample data is already loaded. Run with SAMPLE_ACTION=remove first to reload it.')
        return
    Employee = env['hr.employee'].sudo()  # noqa: F821
    pastor = staff_by_email(TEST_PASTOR_EMAIL) or Employee.search(
        [('staff_role', '=', 'pastor'), ('is_app_active', '=', True)], limit=1)
    finance = staff_by_email(TEST_FINANCE_EMAIL) or Employee.search(
        [('staff_role', '=', 'finance_officer')], limit=1)
    admin = Employee.search([('staff_role', '=', 'admin'), ('is_app_active', '=', True)], limit=1)
    has_ops = has('res.partner', 'church_next_contact_date')

    # ── Families and members ──────────────────────────────────
    families = [
        ('Masih', [('Imran', 'male', 'married', 'leader', 'spouse', 'Electrician'),
                   ('Saima', 'female', 'married', 'member', 'spouse', 'Teacher'),
                   ('Danish', 'male', 'single', 'member', 'son', 'Student'),
                   ('Mehwish', 'female', 'single', 'new_convert', 'daughter', 'Student')]),
        ('Gill', [('Samuel', 'male', 'married', 'worker', 'spouse', 'Accountant'),
                  ('Rubina', 'female', 'married', 'member', 'spouse', 'Nurse'),
                  ('Joel', 'male', 'single', 'member', 'son', 'Student')]),
        ('Bhatti', [('Yousaf', 'male', 'widowed', 'member', 'father', 'Retired'),
                    ('Naveed', 'male', 'married', 'leader', 'son', 'Shopkeeper'),
                    ('Shazia', 'female', 'married', 'member', 'spouse', 'Tailor')]),
        ('Khokhar', [('Pervaiz', 'male', 'married', 'member', 'spouse', 'Driver'),
                     ('Nasreen', 'female', 'married', 'worker', 'spouse', 'Homemaker'),
                     ('Sana', 'female', 'single', 'member', 'daughter', 'Nurse')]),
        ('Sahotra', [('Asher', 'male', 'single', 'member', 'other', 'Software developer'),
                     ('Kiran', 'female', 'single', 'new_convert', 'sister', 'Beautician')]),
        ('Nazir', [('Emmanuel', 'male', 'married', 'member', 'spouse', 'Mechanic'),
                   ('Farah', 'female', 'married', 'inactive', 'spouse', 'Homemaker'),
                   ('Ashir', 'male', 'single', 'member', 'son', 'Student')]),
    ]
    members, number = [], 0
    for f_index, (surname, people) in enumerate(families):
        family = make('church.family', {'name': '%s Family (Sample)' % surname})
        for p_index, (first, gender, marital, status, relation, job) in enumerate(people):
            number += 1
            age = 45 if relation in ('father',) else 38 if relation == 'spouse' else 26
            age += (number * 3) % 9
            dob = date(today.year - age, ((number * 5) % 12) + 1, ((number * 7) % 27) + 1)
            if number in (2, 9):  # birthdays this week for the celebrations card
                soon = today + timedelta(days=1 if number == 2 else 3)
                dob = date(today.year - age, soon.month, soon.day)
            vals = {
                'name': '%s %s (Sample)' % (first, surname),
                'email': '%s.%s.sample@example.invalid' % (first.lower(), surname.lower()),
                'phone': '+92 300 00%05d' % (1000 + number),
                'city': ['Lahore', 'Karachi', 'Faisalabad', 'Gujranwala'][f_index % 4],
                'is_member': True, 'membership_status': status, 'gender': gender,
                'marital_status': marital, 'occupation': job, 'family_id': family.id,
                'is_family_head': p_index == 0, 'family_relationship': relation,
                'family_verified': False,  # set after the SAMPLE number (keeps the sequence)
                'member_join_date': today - timedelta(days=200 + number * 60),
                'date_of_birth': dob,
            }
            if number == 1:
                vals['wedding_anniversary'] = date(today.year - 15, (today + timedelta(days=2)).month,
                                                   (today + timedelta(days=2)).day)
            if status in ('member', 'worker', 'leader') and number % 2:
                vals['water_baptism_date'] = today - timedelta(days=400 + number * 30)
            if number == 7:
                vals['care_status'] = 'hospitalized'
            if number == 12:
                vals['care_status'] = 'needs_follow_up'
            partner = make('res.partner', vals)
            partner.with_context(allow_member_number=True).write({'member_number': 'SAMPLE-%02d' % number})
            partner.write({'family_verified': True})
            if p_index == 0:
                family.write({'head_id': partner.id})
            members.append(partner)
    # One relative added "by a member" and waiting for the church to verify.
    pending = make('res.partner', {
        'name': 'Ayesha Masih (Sample)', 'is_member': True, 'membership_status': 'member',
        'gender': 'female', 'family_id': members[0].family_id.id, 'family_relationship': 'daughter',
        'family_verified': False, 'added_by_partner_id': members[0].id,
        'date_of_birth': date(today.year - 12, 3, 14)})
    pending.with_context(allow_member_number=True).write({'member_number': 'SAMPLE-PENDING'})

    # ── Visitors at each stage ────────────────────────────────
    visitors = []
    for i, (name, stage, source, days) in enumerate([
            ('Bilal Javed', 'new', 'friend', 5), ('Maria Daniel', 'new', 'social', 2),
            ('Tariq Aslam', 'contacted', 'walk_in', 16), ('Hina Pervaiz', 'returning', 'family', 40),
            ('Zubair Lal', 'not_interested', 'event', 70)]):
        vals = {'name': '%s (Sample)' % name, 'phone': '+92 301 00%05d' % (2000 + i),
                'visitor_stage': stage, 'visitor_source': source,
                'first_visit_date': today - timedelta(days=days),
                'visitor_notes': 'Sample visitor for testing follow-up.'}
        if has_ops and stage in ('new', 'contacted'):
            vals['church_next_contact_date'] = today + timedelta(days=i - 1)
            if pastor:
                vals['church_visitor_owner_id'] = pastor.id
        visitor = make('res.partner', vals)
        if pastor:
            visitor.write({'visitor_added_by_id': pastor.id})
        visitors.append(visitor)

    # ── Cell groups and pastor assignments ────────────────────
    for name, leader, roster, day, place in [
            ('Lahore East Cell (Sample)', 0, [0, 1, 2, 3, 13, 14], 'wednesday', 'Masih home, Lahore'),
            ('Youth Fellowship (Sample)', 9, [2, 3, 6, 9, 15, 18, 19], 'friday', 'Church hall'),
            ('Women of Faith (Sample)', 4, [1, 5, 9, 12, 16, 18], 'thursday', 'Gill home, Karachi')]:
        make('cell.group', {'name': name, 'leader_id': members[leader].id, 'meeting_day': day,
                            'meeting_time': '6:30 PM', 'meeting_location': place,
                            'member_ids': [(6, 0, [members[i].id for i in roster])]})
    if pastor:
        for partner in members[:12]:
            make('pastor.assignment', {'pastor_id': pastor.id, 'member_id': partner.id,
                                       'notes': 'Sample assignment'})

    # ── Services and attendance (last 8 Sundays) ──────────────
    last_sunday = today - timedelta(days=(today.weekday() + 1) % 7 or 7)
    absent_lately = {6, 10, 17}  # members missing the last 4 services → Absent Members
    for week in range(8):
        day = last_sunday - timedelta(weeks=week)
        service = make('church.service', {
            'name': 'Sunday Worship (Sample)', 'service_type': 'sabbath_worship',
            'date_start': utc(day, 10), 'date_end': utc(day, 12), 'location': 'Main hall'})
        for i, partner in enumerate(members):
            if (i in absent_lately and week < 4) or (i + week) % 6 == 5:
                continue
            make('church.event.attendance', {'event_id': service.id, 'member_id': partner.id,
                                             'check_in_time': utc(day, 10) + timedelta(minutes=i % 20),
                                             'method': 'qr' if i % 3 else 'manual'})
        if week < 3:  # returning visitor attended recently
            make('church.event.attendance', {'event_id': service.id, 'member_id': visitors[3].id,
                                             'check_in_time': utc(day, 10), 'method': 'manual'})
    next_sunday = last_sunday + timedelta(weeks=1)
    make('church.service', {'name': 'Sunday Worship (Sample)', 'service_type': 'sabbath_worship',
                            'date_start': utc(next_sunday, 10), 'date_end': utc(next_sunday, 12),
                            'location': 'Main hall'})

    # ── Care: prayer requests and pastoral notes ──────────────
    for i, (who, subject, category, status) in enumerate([
            (6, 'Healing after surgery', 'healing', 'praying'),
            (12, 'Job interview next week', 'work', 'assigned'),
            (3, 'Exams and studies', 'work', 'submitted'),
            (9, 'Thank God for a new baby', 'thanksgiving', 'answered')]):
        vals = {'name': members[who].name, 'partner_id': members[who].id, 'subject': subject,
                'message': 'Sample prayer request for testing. Please pray about: %s.' % subject.lower(),
                'visibility': 'prayer_team', 'urgency': 'normal', 'category': category,
                'care_status': status}
        if status == 'answered':
            vals['testimony'] = 'God answered — sample testimony.'
        make('prayer.request', vals)
    if pastor:
        for who, kind, text, follow in [
                (6, 'hospital', 'Visited at the hospital and prayed with the family.', 3),
                (12, 'call', 'Called about job stress; will check in after the interview.', 7),
                (17, 'visit', 'Home visit — has not been to church for a month.', -1)]:
            make('pastoral.care.note', {
                'member_id': members[who].id, 'author_id': pastor.id, 'note_type': kind,
                'date': today - timedelta(days=2), 'content': text + ' (Sample)',
                'follow_up_date': today + timedelta(days=follow),
                'follow_up_assigned_to_id': pastor.id})

    # ── Giving: pledges and donations ─────────────────────────
    Category = env['church.give.category'].sudo()  # noqa: F821
    category = Category.search([], limit=1)
    funds = env['church.give.fund'].sudo().search([('is_active', '=', True)], limit=2)  # noqa: F821
    pledges = []
    for who, amount, freq, status, months in [(0, 5000, 'monthly', 'active', 6),
                                              (4, 3000, 'monthly', 'overdue', 4),
                                              (7, 100000, 'one_time', 'active', 2)]:
        pledges.append(make('church.give.pledge', {
            'member_id': members[who].id, 'pledge_amount': amount, 'currency': 'PKR',
            'frequency': freq, 'status': status, 'start_date': today - timedelta(days=30 * months),
            'fund_id': funds[0].id if funds else False,
            'notes': 'Sample pledge for testing.'}))
    if category:
        gifts = [(0, 5000, 'cash', 3, 0), (0, 5000, 'bank', 33, 0), (0, 5000, 'bank', 63, 0),
                 (4, 3000, 'easypaisa', 90, 1), (7, 40000, 'bank', 20, 2),
                 (1, 2000, 'cash', 6, None), (2, 1500, 'cash', 13, None), (5, 10000, 'jazzcash', 9, None),
                 (8, 2500, 'cash', 27, None), (11, 7000, 'bank', 45, None), (14, 1000, 'cash', 6, None)]
        for i, (who, amount, gateway, days, pledge) in enumerate(gifts):
            vals = {'partner_id': members[who].id, 'donor_name': members[who].name,
                    'amount': amount, 'currency': 'PKR', 'category_id': category.id,
                    'gateway': gateway, 'state': 'completed',
                    'transaction_date': utc(today - timedelta(days=days), 11),
                    'internal_note': 'Sample donation for testing.'}
            if has('church.give.transaction', 'fund_id') and funds:
                vals['fund_id'] = funds[i % len(funds)].id
            if pledge is not None and has('church.give.transaction', 'pledge_id'):
                vals['pledge_id'] = pledges[pledge].id
            make('church.give.transaction', vals)
        make('church.give.transaction', {
            'partner_id': members[13].id, 'donor_name': members[13].name, 'amount': 3500,
            'currency': 'PKR', 'category_id': category.id, 'gateway': 'bank', 'state': 'pending',
            'transaction_date': utc(today - timedelta(days=1), 9),
            'internal_note': 'Sample pending donation for testing.'})
    else:
        print('No giving category found: skipped sample donations.')

    # ── Expenses and budget (needs Church Finance 1.1) ────────
    if 'church.expense' in env and (pastor or finance or admin):  # noqa: F821
        Expense = env['church.expense'].sudo()  # noqa: F821
        cats = {c.name.split(' ')[0].lower(): c for c in env['church.expense.category'].sudo().search([])}  # noqa: F821
        submitter = pastor or finance or admin
        approver = finance if finance and finance != submitter else admin
        for desc, cat, amount, state, days in [
                ('October electricity bill', 'utilities', 18500, 'paid', 12),
                ('Sound system repair', 'media', 32000, 'paid', 25),
                ('Youth outreach snacks', 'children', 8000, 'submitted', 2),
                ('Welfare ration bags', 'welfare', 45000, 'approved', 4),
                ('Hall rent for revival meeting', 'rent', 75000, 'submitted', 1),
                ('Printing tracts', 'office', 6000, 'rejected', 6),
                ('Pastor travel to village church', 'travel', 4500, 'draft', 0)]:
            category_rec = cats.get(cat) or next(iter(cats.values()), None)
            if not category_rec:
                break
            expense = make('church.expense', {
                'description': desc + ' (Sample)', 'category_id': category_rec.id, 'amount': amount,
                'currency': 'PKR', 'amount_pkr': amount, 'date': today - timedelta(days=days),
                'payee': 'Sample vendor', 'submitted_by_id': submitter.id})
            internal = expense.with_context(church_expense_internal=True)
            steps = {'submitted': ['submitted'], 'approved': ['submitted', 'approved'],
                     'paid': ['submitted', 'approved', 'paid'],
                     'rejected': ['submitted', 'rejected']}.get(state, [])
            for step in steps:
                vals = {'state': step}
                if step == 'submitted':
                    vals['submitted_at'] = datetime.now()
                elif step == 'approved' and approver:
                    vals.update(approved_by_id=approver.id, approved_at=datetime.now())
                elif step == 'paid' and approver:
                    vals.update(paid_by_id=approver.id, paid_at=datetime.now(), method='bank')
                elif step == 'rejected':
                    vals['rejected_reason'] = 'Please attach the printer bill.'
                internal.write(vals)
            for log in expense.log_ids:
                track(log)
        Budget = env['church.budget'].sudo()  # noqa: F821
        if not Budget.search_count([('year', '=', today.year)]):
            plan = {'salaries': 1200000, 'utilities': 220000, 'rent': 300000, 'repairs': 80000,
                    'worship': 60000, 'outreach': 150000, 'welfare': 120000, 'children': 50000,
                    'media': 40000, 'office': 30000, 'travel': 45000}
            budget = make('church.budget', {'year': today.year, 'notes': 'Sample budget for testing.'})
            for key, amount in plan.items():
                if key in cats:
                    make('church.budget.line', {'budget_id': budget.id, 'category_id': cats[key].id,
                                                'amount': amount})
        else:
            print('A %s budget already exists: left it unchanged.' % today.year)
    elif 'church.expense' not in env:  # noqa: F821
        print('Church Finance 1.1 is not installed yet: skipped sample expenses and budget.')

    env.cr.commit()  # noqa: F821
    print('Sample data loaded:')
    for model, count in sorted(counter.items()):
        print('  %-26s %d' % (model, count))
    if not pastor:
        print('No pastor found: create the test pastor (%s) and reload to get assignments '
              'and care notes.' % TEST_PASTOR_EMAIL)


def remove():
    entries = Data.search([('module', '=', MODULE)])
    if not entries:
        print('No sample data found.')
        return
    by_model = {}
    for entry in entries:
        by_model.setdefault(entry.model, []).append(entry.res_id)
    removed = {}
    for model in REMOVE_ORDER + sorted(set(by_model) - set(REMOVE_ORDER)):
        ids = by_model.get(model)
        if not ids or model not in env:  # noqa: F821
            continue
        records = env[model].sudo().browse(ids).exists()  # noqa: F821
        if model == 'church.expense':
            # Paid expenses are locked against deletion in the app on purpose;
            # remove only these tracked sample rows directly (history cascades).
            if records.ids:
                env.cr.execute('DELETE FROM church_expense WHERE id IN %s', [tuple(records.ids)])  # noqa: F821
        elif model == 'church.expense.log':
            continue  # deleted together with their expenses
        else:
            records.unlink()
        removed[model] = len(records)
    entries.unlink()
    env.cr.commit()  # noqa: F821
    print('Sample data removed:')
    for model, count in sorted(removed.items()):
        print('  %-26s %d' % (model, count))


action = os.environ.get('SAMPLE_ACTION', '').strip().lower()
if action == 'load':
    load()
elif action == 'remove':
    remove()
else:
    print('Set SAMPLE_ACTION=load or SAMPLE_ACTION=remove.')
