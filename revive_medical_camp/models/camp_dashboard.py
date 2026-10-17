"""Eagle-eye dashboard: every number about one camp (or all camps) in one call.

Coordinators and the medical lead (which includes system administrators)
already see all camp data, so the dashboard reads with sudo after that
check and returns totals; patient names appear only in the "waiting
longest" and "red flag" lists that coordinators run anyway."""
from collections import Counter, defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

ACTIVE_STATES = ('registered', 'triaged', 'with_doctor', 'at_pharmacy')
SEEN_EXCLUDED = ('cancelled', 'booked')
FLOW = [('booked', 'Pre-registered'), ('registered', 'Waiting for triage'), ('triaged', 'Waiting for doctor'),
        ('with_doctor', 'With doctor'), ('at_pharmacy', 'At pharmacy'), ('done', 'Done'),
        ('referred', 'Referred')]
AGE_BANDS = [(0, 4, '0-4'), (5, 14, '5-14'), (15, 29, '15-29'), (30, 44, '30-44'),
             (45, 59, '45-59'), (60, 200, '60+')]
LOW_STOCK_UNITS = 20
EXPIRY_WARNING_DAYS = 60


def _minutes(delta):
    return round(delta.total_seconds() / 60.0, 1)


# Longer than this means a visit was left open (e.g. not finished on the day),
# not a real wait; such visits are left out of the average waiting times.
MAX_REAL_WAIT_MINUTES = 12 * 60


def _avg(values):
    values = [v for v in values if v is not None and 0 <= v <= MAX_REAL_WAIT_MINUTES]
    return round(sum(values) / len(values), 1) if values else None


class CampDashboard(models.AbstractModel):
    _name = 'camp.dashboard'
    _description = 'Medical camp dashboard'

    @api.model
    def _check_access(self):
        user = self.env.user
        if not (user.has_group('revive_medical_camp.group_camp_coordinator')
                or user.has_group('base.group_system')):
            raise AccessError(_('The camp dashboard is for camp coordinators and the medical lead.'))

    @api.model
    def _default_camp(self, Camp):
        return (Camp.search([('state', '=', 'running')], order='date_start desc', limit=1)
                or Camp.search([('state', '=', 'ready')], order='date_start asc', limit=1)
                or Camp.search([], order='date_start desc, id desc', limit=1))

    @api.model
    def get_dashboard(self, camp_id=None):
        """camp_id: a camp id, 'all' for every camp, or None for the live camp."""
        self._check_access()
        Camp = self.env['camp.camp'].sudo()
        camps = Camp.search([], order='date_start desc, id desc')
        if camp_id == 'all':
            selected = camps
            mode = 'all'
        else:
            selected = Camp.browse(int(camp_id)).exists() if camp_id else self._default_camp(Camp)
            mode = 'camp'
        currency = (selected[:1].currency_id or self.env.company.currency_id)
        result = {
            'mode': mode,
            'camp_id': selected.id if mode == 'camp' and selected else None,
            'camps': [{'id': c.id, 'name': c.name, 'date': str(c.date_start or ''), 'state': c.state}
                      for c in camps],
            'currency': currency.symbol or currency.name or '',
            'generated_at': fields.Datetime.to_string(fields.Datetime.now()),
            'all_camps': self._all_camps(camps),
        }
        if not selected:
            result['empty'] = True
            return result
        Visit = self.env['camp.visit'].sudo()
        visits = Visit.search([('camp_id', 'in', selected.ids)])
        seen = visits.filtered(lambda v: v.state not in SEEN_EXCLUDED)
        result.update(
            header=self._header(selected, mode),
            kpis=self._kpis(selected, visits, seen),
            flow=self._flow(visits),
            day=self._day(selected, visits, mode),
            clinical=self._clinical(selected, seen),
            pharmacy=self._pharmacy(selected, seen, mode),
            team=self._team(selected, mode),
            followup=self._followup(selected),
            money=self._money(selected),
            live=mode == 'camp' and selected.state == 'running',
        )
        return result

    # ── Sections ────────────────────────────────────────────────

    def _header(self, camps, mode):
        if mode == 'all':
            dated = camps.filtered('date_start').sorted('date_start')
            return {'title': _('All camps'), 'count': len(camps),
                    'first': str(dated[:1].date_start or ''), 'last': str(dated[-1:].date_start or ''),
                    'areas': sorted({c.area for c in camps if c.area})}
        camp = camps
        return {'title': camp.name, 'state': camp.state,
                'state_label': dict(camp._fields['state']._description_selection(self.env)).get(camp.state),
                'date_start': str(camp.date_start or ''), 'date_end': str(camp.date_end or ''),
                'site': camp.site or '', 'area': camp.area or '',
                'coordinator': camp.coordinator_id.name or '',
                'sponsors': camp.sponsor_ids.mapped('name'),
                'specialities': camp.speciality_ids.mapped('name')}

    def _kpis(self, camps, visits, seen):
        today = fields.Date.context_today(self)
        followups = self.env['camp.followup'].sudo().search([('camp_id', 'in', camps.ids),
                                                             ('state', 'in', ['to_call', 'no_answer'])])
        referrals = self.env['camp.referral'].sudo().search([('camp_id', 'in', camps.ids)])
        expected = sum(camps.mapped('expected_patients'))
        total_cost = sum(camps.mapped('total_cost'))
        return {
            'patients_seen': len(seen), 'expected': expected,
            'progress': round(len(seen) * 100.0 / expected, 1) if expected else None,
            'waiting_now': len(visits.filtered(lambda v: v.state in ACTIVE_STATES)),
            'red_flags': len(seen.filtered('flag_rule_ids')),
            'urgent_waiting': len(visits.filtered(lambda v: v.state in ACTIVE_STATES and v.priority == 'urgent')),
            'referrals': len(referrals),
            'urgent_referrals': len(referrals.filtered(lambda r: r.urgency == 'urgent')),
            'medicines_units': sum(camps.mapped('medicines_dispensed')),
            'medicines_value': sum(camps.mapped('medicines_value')),
            'total_cost': total_cost,
            'cost_per_patient': round(total_cost / len(seen), 2) if seen else 0.0,
            'followups_due': len(followups.filtered(lambda f: not f.due_date or f.due_date <= today)),
            'followups_overdue': len(followups.filtered(lambda f: f.due_date and f.due_date < today)),
            'first_visits': len(seen.filtered('is_first_visit')),
        }

    def _flow(self, visits):
        now = fields.Datetime.now()
        counts = Counter(visits.mapped('state'))
        triage_waits, doctor_waits, total_times = [], [], []
        for visit in visits.filtered(lambda v: v.arrived_at and v.state not in SEEN_EXCLUDED):
            vitals = visit.vitals_ids.sorted('create_date')[:1]
            consult = visit.consultation_ids.sorted('create_date')[:1]
            if vitals:
                triage_waits.append(_minutes(vitals.create_date - visit.arrived_at))
            if consult:
                start = vitals.create_date if vitals else visit.arrived_at
                doctor_waits.append(_minutes(consult.create_date - start))
            if visit.state in ('done', 'referred'):
                total_times.append(_minutes(visit.write_date - visit.arrived_at))
        waiting = visits.filtered(lambda v: v.state in ACTIVE_STATES).sorted(
            lambda v: (-v.priority_rank, v.arrived_at or now))
        return {
            'stages': [{'key': key, 'label': label, 'count': counts.get(key, 0)} for key, label in FLOW],
            'avg_wait_triage': _avg(triage_waits), 'avg_wait_doctor': _avg(doctor_waits),
            'avg_visit_time': _avg(total_times),
            'longest': [{
                'id': v.id, 'token': v.token_no, 'name': v.patient_id.name, 'state': v.state,
                'state_label': dict(FLOW).get(v.state, v.state), 'priority': v.priority,
                'minutes': _minutes(now - v.arrived_at) if v.arrived_at else None,
                'flags': v.flag_rule_ids.mapped('name'),
            } for v in waiting[:6]],
            'red_flag_list': [{
                'id': v.id, 'token': v.token_no, 'name': v.patient_id.name, 'state': v.state,
                'state_label': dict(FLOW).get(v.state, v.state), 'flags': v.flag_rule_ids.mapped('name'),
            } for v in visits.filtered(lambda v: v.flag_rule_ids and v.state in ACTIVE_STATES)[:8]],
        }

    def _day(self, camps, visits, mode):
        if mode == 'all':
            rows = [{'label': c.name, 'date': str(c.date_start or ''), 'value': c.patients_seen}
                    for c in camps.sorted(lambda c: c.date_start or fields.Date.today())]
            return {'kind': 'camps', 'rows': rows[-12:]}
        local = lambda dt: fields.Datetime.context_timestamp(self, dt)  # noqa: E731
        stamped = visits.filtered(lambda v: v.arrived_at and v.state not in SEEN_EXCLUDED)
        if not stamped:
            return {'kind': 'hours', 'rows': [], 'day': ''}
        today = fields.Date.context_today(self)
        days = sorted({local(v.arrived_at).date() for v in stamped})
        day = today if today in days else days[-1]
        arrived, finished = Counter(), Counter()
        for v in stamped:
            if local(v.arrived_at).date() == day:
                arrived[local(v.arrived_at).hour] += 1
            if v.state in ('done', 'referred') and local(v.write_date).date() == day:
                finished[local(v.write_date).hour] += 1
        hours = sorted(set(arrived) | set(finished))
        span = range(min(hours), max(hours) + 1) if hours else []
        return {'kind': 'hours', 'day': str(day), 'rows': [
            {'hour': h, 'label': '%02d:00' % h, 'arrived': arrived.get(h, 0), 'finished': finished.get(h, 0)}
            for h in span]}

    def _clinical(self, camps, seen):
        env = self.env
        consults = env['camp.consultation'].sudo().search([('camp_id', 'in', camps.ids)])
        diagnoses = Counter()
        for consult in consults:
            for code in consult.diagnosis_ids:
                diagnoses[code.display_name] += 1
        ages = {label: {'male': 0, 'female': 0, 'other': 0} for _lo, _hi, label in AGE_BANDS}
        for visit in seen:
            age, sex = visit.patient_id.age_years or 0, visit.patient_id.sex or 'other'
            for lo, hi, label in AGE_BANDS:
                if lo <= age <= hi:
                    ages[label][sex if sex in ('male', 'female') else 'other'] += 1
                    break
        flags = Counter(name for v in seen for name in v.flag_rule_ids.mapped('name'))
        referrals = env['camp.referral'].sudo().search([('camp_id', 'in', camps.ids)])
        labs = env['camp.lab.order'].sudo().search([('camp_id', 'in', camps.ids)])
        test_labels = dict(labs._fields['test']._description_selection(env))
        lab_rows = defaultdict(lambda: {'ordered': 0, 'done': 0, 'abnormal': 0})
        for order in labs.filtered(lambda o: o.state != 'cancelled'):
            row = lab_rows[test_labels.get(order.test, order.test) if order.test != 'other' else (order.test_name or 'Other')]
            row['ordered'] += 1
            row['done'] += order.state == 'done'
            row['abnormal'] += order.abnormal
        eyes = env['camp.eye.exam'].sudo().search([('camp_id', 'in', camps.ids)])
        anc = env['camp.anc.check'].sudo().search([('camp_id', 'in', camps.ids)])
        vaccines = env['camp.vaccine.record'].sudo().search([('camp_id', 'in', camps.ids)])
        talks = env['camp.education.session'].sudo().search([('camp_id', 'in', camps.ids)])
        sexes = Counter(v.patient_id.sex or 'other' for v in seen)
        return {
            'diagnoses': [{'label': k, 'value': n} for k, n in diagnoses.most_common(10)],
            'ages': [{'label': label, **ages[label]} for _lo, _hi, label in AGE_BANDS],
            'sexes': {'male': sexes.get('male', 0), 'female': sexes.get('female', 0),
                      'other': sum(n for s, n in sexes.items() if s not in ('male', 'female'))},
            'children': len(seen.filtered(lambda v: (v.patient_id.age_years or 0) < 15)),
            'pregnant': len(seen.filtered('pregnant')),
            'flags': [{'label': k, 'value': n} for k, n in flags.most_common(8)],
            'referral_hospitals': [{'label': k, 'value': n} for k, n in
                                   Counter(r.hospital_id.name or '-' for r in referrals).most_common(6)],
            'referral_departments': [{'label': k, 'value': n} for k, n in
                                     Counter((r.department or 'General') for r in referrals).most_common(6)],
            'referral_status': dict(Counter(referrals.mapped('status'))),
            'labs': [{'label': k, **v} for k, v in sorted(lab_rows.items(), key=lambda kv: -kv[1]['ordered'])],
            'eye': {'exams': len(eyes), 'needs_specialist': len(eyes.filtered('needs_specialist')),
                    'glasses_given': len(eyes.filtered('glasses_id'))},
            'anc': {'checks': len(anc), 'high_risk': len(anc.filtered('high_risk')),
                    'tt_given': len(anc.filtered('tt_given'))},
            'vaccines': {'given': len(vaccines.filtered(lambda r: r.status == 'given')),
                         'missed': len(vaccines.filtered(lambda r: r.status == 'missed')),
                         'had': len(vaccines.filtered(lambda r: r.status == 'had'))},
            'talks': {'sessions': len(talks), 'attendees': sum(talks.mapped('attendees_count')),
                      'topics': talks.mapped('topic')[:6]},
            'consultations': len(consults.filtered(lambda c: c.state == 'done')),
        }

    def _pharmacy(self, camps, seen, mode):
        lines = self.env['camp.prescription.line'].sudo().search([('camp_id', 'in', camps.ids)])
        dispensed = Counter()
        for line in lines.filtered(lambda l: l.dispensed_qty > 0):
            dispensed[(line.substitute_formulary_id or line.formulary_id).display_name or '-'] += line.dispensed_qty
        state_counts = Counter(lines.mapped('state'))
        result = {
            'top_medicines': [{'label': k, 'value': round(n, 1)} for k, n in dispensed.most_common(10)],
            'lines': {'prescribed': len(lines), 'to_dispense': state_counts.get('prescribed', 0),
                      'dispensed': state_counts.get('dispensed', 0), 'partial': state_counts.get('partial', 0),
                      'not_given': state_counts.get('not_given', 0), 'outside': state_counts.get('outside', 0)},
            'stock': [], 'low_stock': [], 'expiring': [], 'expired': [],
        }
        counts = self.env['camp.stock.count'].sudo().search([('camp_id', 'in', camps.ids)], order='counted_at desc')
        result['stock_counts'] = {'count': len(counts), 'last': str(counts[:1].counted_at or ''),
                                  'differences': counts[:1].difference_count if counts else 0}
        location = camps.stock_location_id if mode == 'camp' else False
        if not location:
            return result
        quants = self.env['stock.quant'].sudo().search([('location_id', 'child_of', location.id),
                                                        ('quantity', '>', 0)])
        now = fields.Datetime.now()
        soon = now + timedelta(days=EXPIRY_WARNING_DAYS)
        per_product = defaultdict(float)
        for quant in quants:
            per_product[quant.product_id] += quant.quantity
            expiry = quant.lot_id.expiration_date if quant.lot_id and 'expiration_date' in quant.lot_id._fields else False
            if expiry:
                row = {'product': quant.product_id.display_name, 'lot': quant.lot_id.name,
                       'qty': quant.quantity, 'expiry': str(expiry.date())}
                if expiry < now:
                    result['expired'].append(row)
                elif expiry <= soon:
                    result['expiring'].append(row)
        formulary = self.env['camp.formulary'].sudo().search([])
        for item in formulary:
            qty = per_product.get(item.product_id, 0.0)
            row = {'product': item.display_name, 'qty': qty}
            if qty <= LOW_STOCK_UNITS:
                result['low_stock'].append(row)
        result['low_stock'].sort(key=lambda r: r['qty'])
        result['expiring'].sort(key=lambda r: r['expiry'])
        result['stock'] = sorted(({'product': p.display_name, 'qty': q} for p, q in per_product.items()),
                                 key=lambda r: r['qty'])[:12]
        result['low_stock_limit'] = LOW_STOCK_UNITS
        result['expiry_days'] = EXPIRY_WARNING_DAYS
        return result

    def _team(self, camps, mode):
        members = self.env['camp.team.member'].sudo().search([('camp_id', 'in', camps.ids)])
        role_labels = dict(members._fields['role']._description_selection(self.env))
        consults = self.env['camp.consultation'].sudo().search(
            [('camp_id', 'in', camps.ids), ('state', '=', 'done')])
        # One count per consultation (mapped() would merge repeat doctors).
        per_doctor = Counter(c.doctor_id.name for c in consults)
        return {
            'size': len(members),
            'roles': [{'label': role_labels.get(r, r), 'value': n}
                      for r, n in Counter(members.mapped('role')).most_common()],
            'per_doctor': [{'label': k or '-', 'value': n} for k, n in per_doctor.most_common(8)],
            'on_duty': [] if mode == 'all' else [{
                'name': m.name, 'role': role_labels.get(m.role, m.role),
                'shift': ('%02d:%02d-%02d:%02d' % (int(m.shift_start), round(m.shift_start % 1 * 60),
                                                   int(m.shift_end), round(m.shift_end % 1 * 60)))
                if m.shift_end else '',
            } for m in members.sorted(lambda m: (m.role, m.name))],
            'licence_warnings': [{'name': m.name, 'warning': m.pmdc_warning}
                                 for m in members if m.pmdc_warning],
        }

    def _followup(self, camps):
        followups = self.env['camp.followup'].sudo().search([('camp_id', 'in', camps.ids)])
        today = fields.Date.context_today(self)
        kinds = dict(followups._fields['kind']._description_selection(self.env))
        states = dict(followups._fields['state']._description_selection(self.env))
        open_ = followups.filtered(lambda f: f.state in ('to_call', 'no_answer'))
        return {
            'total': len(followups),
            'states': [{'key': k, 'label': states.get(k, k), 'value': n}
                       for k, n in Counter(followups.mapped('state')).most_common()],
            'kinds': [{'label': kinds.get(k, k), 'value': n}
                      for k, n in Counter(followups.mapped('kind')).most_common()],
            'overdue': len(open_.filtered(lambda f: f.due_date and f.due_date < today)),
            'due_today': len(open_.filtered(lambda f: f.due_date == today)),
            'reached_rate': round(len(followups.filtered(lambda f: f.state in ('reached', 'closed')))
                                  * 100.0 / len(followups), 1) if followups else None,
        }

    def _money(self, camps):
        lines = self.env['camp.budget.line'].sudo().search([('camp_id', 'in', camps.ids)])
        labels = dict(lines._fields['category']._description_selection(self.env))
        by_category = defaultdict(lambda: {'planned': 0.0, 'actual': 0.0})
        for line in lines:
            by_category[line.category]['planned'] += line.planned
            by_category[line.category]['actual'] += line.actual
        planned, actual = sum(camps.mapped('budget_planned')), sum(camps.mapped('budget_actual'))
        seen = sum(camps.mapped('patients_seen'))
        total = sum(camps.mapped('total_cost'))
        return {
            'planned': planned, 'actual': actual,
            'used_percent': round(actual * 100.0 / planned, 1) if planned else None,
            'medicines_value': sum(camps.mapped('medicines_value')),
            'total_cost': total, 'cost_per_patient': round(total / seen, 2) if seen else 0.0,
            'categories': [{'label': labels.get(k, k), **v} for k, v in
                           sorted(by_category.items(), key=lambda kv: -max(kv[1]['planned'], kv[1]['actual']))],
            'sponsors': sorted(set(camps.mapped('sponsor_ids.name'))),
        }

    def _all_camps(self, camps):
        rows = [{
            'id': c.id, 'name': c.name, 'date': str(c.date_start or ''), 'area': c.area or '',
            'state': c.state, 'patients': c.patients_seen, 'expected': c.expected_patients,
            'referrals': c.referral_count, 'flagged': c.flagged_count,
            'cost_per_patient': round(c.cost_per_patient, 2), 'total_cost': c.total_cost,
        } for c in camps]
        return {'rows': rows, 'totals': {
            'camps': len(rows), 'patients': sum(r['patients'] for r in rows),
            'referrals': sum(r['referrals'] for r in rows), 'flagged': sum(r['flagged'] for r in rows),
            'total_cost': sum(r['total_cost'] for r in rows),
        }}
