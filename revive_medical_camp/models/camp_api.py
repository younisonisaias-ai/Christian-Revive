"""Server side of Camp Mode: what a camp phone downloads before the camp, and
how the records it saved offline are uploaded.

Two kinds of camp workers:

* internal users (coordinator, medical lead, ...) - calls run as them, so the
  normal access rights and record rules apply, plus the role checks below;
* portal users (station volunteers and staff who only use the phone app) -
  they have no rights on camp records at all. Calls run with server rights,
  but only for camps whose team they are on, and every read and write is
  checked here against their team role (doctor > nurse > registration).

Uploads are
idempotent: each record carries the phone's own id (client_uuid); sending
the same batch again updates or skips, it never duplicates.
"""
import logging
import re
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError

_logger = logging.getLogger(__name__)

ROLE_GROUPS = [
    ('lead', 'revive_medical_camp.group_camp_lead'),
    ('coordinator', 'revive_medical_camp.group_camp_coordinator'),
    ('doctor', 'revive_medical_camp.group_camp_doctor'),
    ('nurse', 'revive_medical_camp.group_camp_nurse'),
    ('pharmacist', 'revive_medical_camp.group_camp_pharmacist'),
    ('registration', 'revive_medical_camp.group_camp_registration'),
    ('followup', 'revive_medical_camp.group_camp_followup'),
]
# Team role of a portal worker -> what they may do (same as the internal groups).
TEAM_ROLE_RIGHTS = {
    'registration': {'registration'},
    'nurse': {'nurse', 'registration'},
    'doctor': {'doctor', 'nurse', 'registration'},
    'pharmacist': {'pharmacist'},
    'followup': {'followup'},
    'educator': {'educator'},
    'coordinator': {'registration', 'followup'},   # closing / reports need an internal login
    'helper': set(),
}
# Which roles may read each kind of record.
READ_RIGHTS = {
    'camp.vitals': {'nurse', 'doctor'},
    'camp.consultation': {'doctor', 'pharmacist'},
    'camp.prescription.line': {'doctor', 'pharmacist'},
    'camp.referral': {'doctor', 'followup', 'coordinator'},
    'camp.followup': {'followup', 'doctor', 'coordinator'},
    'camp.rx.template': {'doctor'},
    'camp.lab.order': {'nurse', 'doctor'},
    'camp.reminder': {'followup', 'coordinator'},
    'camp.eye.exam': {'eye', 'doctor'},
    'camp.glasses': {'eye'},
    'camp.anc.check': {'nurse', 'doctor'},
    'camp.vaccine.record': {'nurse', 'doctor'},
}
MAX_ITEMS = 500           # per kind, per upload
RETURNING_PATIENTS = 3000  # patients from the camp's area sent to phones
RETURNING_YEARS = 2        # only patients seen (or registered) in the last 2 years
FOLLOWUP_DAYS = 60         # closed camps stay in Camp Mode this long for follow-up calls

PATIENT_FIELDS = ['name', 'date_of_birth', 'age_years', 'sex', 'phone', 'area', 'guardian_name',
                  'consent_care', 'consent_media', 'consent_messages', 'allergies']
VITAL_FIELDS = ['bp_systolic', 'bp_diastolic', 'pulse', 'temperature', 'spo2', 'weight', 'height',
                'blood_sugar', 'hemoglobin', 'urine_dipstick', 'vision_left', 'vision_right', 'notes']
CONSULT_FIELDS = ['complaint', 'history', 'examination', 'advice', 'advice_ur',
                  'follow_up_needed', 'follow_up_reason']
LINE_FIELDS = ['days', 'quantity', 'instructions_ur', 'outside_medicine']
FULL_DIAGNOSIS_ROLES = {'doctor', 'pharmacist', 'lead'}   # others only get the common list
REFERRAL_FIELDS = ['department', 'reason', 'urgency', 'status', 'outcome']
SESSION_FIELDS = ['topic', 'educator', 'start_time', 'attendees_count']


class _Batch:
    """State of one upload: warnings and consultations to finish."""

    def __init__(self, env):
        self.warnings = []
        self.to_finish = env['camp.consultation']

    def warn(self, kind, item, message):
        self.warnings.append({'kind': kind, 'client_uuid': item.get('client_uuid'), 'message': message})


class CampApi(models.AbstractModel):
    _name = 'camp.api'
    _description = 'Camp Mode sync service'

    # ── Who is this? ────────────────────────────────────────────
    @api.model
    def _roles(self, user=None):
        """Roles of the worker. Inside a camp call this is fixed in the context
        (portal: their team role in that camp)."""
        if user is None and self.env.context.get('camp_roles') is not None:
            return list(self.env.context['camp_roles'])
        user = user or self.env.user
        team = self._team_rights(user, self.env['camp.camp'].sudo().search([]))
        if user.share:
            return sorted(team)
        return sorted(self._group_roles(user) | team)

    @api.model
    def _group_roles(self, user):
        """Rights an office user has from their Odoo access rights (not the tab)."""
        return {role for role, xmlid in ROLE_GROUPS if user.has_group(xmlid)}

    @api.model
    def _team_rights(self, user, camps):
        """Stations switched on for this person on the camps' Permissions tab."""
        return camps.sudo().team_member_ids.filtered(lambda m: m.user_id == user)._rights()

    @api.model
    def _is_camp_worker(self, user=None):
        """May this login use Camp Mode at all?"""
        user = user or self.env.user
        on_team = bool(self.env['camp.team.member'].sudo().search_count([('user_id', '=', user.id)]))
        if user.share:
            return on_team
        return bool(self._roles(user)) or on_team

    @api.model
    def _login_candidates(self, typed, limit=5):
        """Logins a worker may mean when typing a login, an email or a phone
        number ("0300-1234567" = "03001234567"). Camp workers come first."""
        typed = (typed or '').strip()
        digits = re.sub(r'[^0-9+]', '', typed)
        Users = self.env['res.users'].sudo().with_context(active_test=True)
        domain = Domain('login', '=ilike', typed)
        if '@' in typed:
            domain |= Domain('email', '=ilike', typed)
        elif len(digits) >= 7:
            domain |= Domain('login', '=', digits) | Domain('phone', '=', digits)
        users = Users.search(domain, limit=limit)
        workers = self.env['camp.team.member'].sudo().search([('user_id', 'in', users.ids)]).user_id
        ordered = sorted(users, key=lambda u: (u.login.lower() != typed.lower(), u not in workers, u.id))
        return [u.login for u in ordered] or [typed]

    def _worker(self, camp_id):
        """(api, camp) to run one camp call with. Portal workers get server
        rights limited to this camp and their team role."""
        if self.env.context.get('camp_ready'):
            return self, self._get_camp(camp_id)
        user = self.env.user
        camp = self.env['camp.camp'].sudo().browse(int(camp_id)).exists()
        if not camp:
            raise MissingError(_('Camp not found.'))
        team = self._team_rights(user, camp) if user in camp.team_member_ids.user_id else None
        if user.share:
            if team is None:
                raise AccessError(_('You are not on the team of this camp.'))
            rights, api_env = team, self.sudo()
        else:
            groups = self._group_roles(user)
            rights = groups | (team or set())
            if 'lead' not in groups and (team or set()) - groups:
                # The Permissions tab gives this office user a station their
                # Odoo role does not cover: run with server rights, checked here.
                api_env = self.sudo()
            elif not groups:
                raise AccessError(_('You are not on the team of this camp.'))
            else:
                api_env = self
        api_env = api_env.with_context(camp_roles=tuple(sorted(rights)), camp_ready=True, camp_scope=int(camp_id))
        return api_env, api_env._get_camp(camp_id)

    def _need(self, *roles):
        have = set(self._roles())
        if 'lead' in have or have & set(roles):
            return
        raise AccessError(_('Your camp role cannot do this.'))

    def _may_read(self, model):
        have = set(self._roles())
        allowed = READ_RIGHTS.get(model)
        if allowed is not None and not ('lead' in have or have & allowed):
            return False
        return bool(have) and (self.env.su or self.env[model].has_access('read'))

    def _check_doctor_registration(self):
        """Consultations need a PMDC number (the model checks internal users;
        portal doctors are checked here)."""
        if self.env.su and not self.env.user.camp_pmdc_number:
            raise ValidationError(_('Add your PMDC number (ask the camp coordinator) before saving a consultation.'))

    @api.model
    def me(self):
        user = self.env.user
        domain = [('state', '!=', 'closed')]
        if {'followup', 'coordinator'} & set(self._roles(user)):
            # Follow-up calls happen after the camp: keep recent closed camps.
            recent = fields.Date.context_today(self) - timedelta(days=FOLLOWUP_DAYS)
            domain = ['|', ('state', '!=', 'closed'), ('date_start', '>=', recent)]
        if user.share or not any(user.has_group(x) for _r, x in ROLE_GROUPS):
            domain = Domain.AND([domain, [('team_member_ids.user_id', '=', user.id)]])
            camps = self.env['camp.camp'].sudo().search(domain, order='date_start')
        else:
            camps = self.env['camp.camp'].search(domain, order='date_start')
        return {
            'user': {
                'id': user.id, 'name': user.name, 'login': user.login,
                'roles': self._roles(user),
                'has_pmdc_number': bool(user.camp_pmdc_number),
                'must_change_password': bool(user.camp_must_change_password),
            },
            'camps': [self._camp(c) for c in camps],
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
        }

    # ── Download ────────────────────────────────────────────────
    @api.model
    def bootstrap(self, camp_id, reserve_tokens=0):
        """Everything a phone needs to run its station offline."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.bootstrap(camp_id, reserve_tokens)
        Env = self.env
        can = self._may_read
        data = {
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
            'camp': self._camp(camp),
            'me': {'id': Env.user.id, 'name': Env.user.name, 'roles': self._roles(),
                   'has_pmdc_number': bool(Env.user.camp_pmdc_number),
                   'pmdc_expiry': fields.Date.to_string(Env.user.camp_pmdc_expiry) if Env.user.camp_pmdc_expiry else None,
                   'team_member_id': camp.sudo().team_member_ids.filtered(lambda m: m.user_id == Env.user)[:1].id or None},
            'team': self._team(camp),
            'flag_rules': [{'id': r.id, 'name': r.name, 'name_ur': r.name_ur or '', 'measure': r.measure,
                            'operator': r.operator, 'value': r.value, 'priority': r.priority}
                           for r in Env['camp.flag.rule'].search([])] if can('camp.flag.rule') else [],
            'dose_templates': [{'id': d.id, 'name': d.name, 'name_ur': d.name_ur or '',
                                'doses_per_day': d.doses_per_day, 'as_needed': d.as_needed}
                               for d in Env['camp.dose.template'].search([])] if can('camp.dose.template') else [],
            'diagnosis_codes': self._diagnosis_list(None) if can('camp.diagnosis.code') else [],
            'formulary': self._formulary(camp) if can('camp.formulary') else [],
            'rx_templates': self._rx_templates(None) if can('camp.rx.template') else [],
            'hospitals': [{'id': p.id, 'name': p.name, 'city': p.city or ''}
                          for p in Env['res.partner'].sudo().search([('camp_is_hospital', '=', True)])],
            'patients': [],
            'token_block': None,
        }
        if can('camp.patient'):
            area_patients = Env['camp.patient'].search(
                self._returning_domain(camp), limit=RETURNING_PATIENTS, order='id desc')                 if camp.area else Env['camp.patient']
            camp_patients = Env['camp.visit'].search([('camp_id', '=', camp.id)]).patient_id
            data['patients'] = self._patients(camp_patients | area_patients, camp)
        if reserve_tokens and 'registration' in self._roles():
            data['token_block'] = camp.sudo()._reserve_tokens(reserve_tokens)
        data.update(self.changes(camp.id, since=None))   # also sets server_time
        self.env['camp.audit.log'].log('download', camp=camp,
                                       details=f'{len(data["patients"])} patients to a phone')
        return data

    @api.model
    def changes(self, camp_id, since=None):
        """Records of this camp changed since `since` (UTC string), so each phone
        sees what the other stations did."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.changes(camp_id, since)
        Env = self.env
        now = fields.Datetime.now()
        dom = [('camp_id', '=', camp.id)]
        if since:
            dom.append(('write_date', '>=', fields.Datetime.to_datetime(since)))
        can = self._may_read
        visits = Env['camp.visit'].search(dom) if can('camp.visit') else Env['camp.visit']
        out = {
            'server_time': fields.Datetime.to_string(now),
            'visits': [self._visit(v) for v in visits],
            'changed_patients': self._patients(visits.patient_id, camp) if since else [],
            'vitals': [self._vitals(r) for r in Env['camp.vitals'].search(dom)] if can('camp.vitals') else [],
            'consultations': [self._consultation(c) for c in Env['camp.consultation'].search(dom)]
            if can('camp.consultation') else [],
            'prescription_lines': [self._line(line) for line in Env['camp.prescription.line'].search(dom)]
            if can('camp.prescription.line') else [],
            'referrals': [self._referral(r) for r in Env['camp.referral'].search(dom)]
            if can('camp.referral') else [],
            'camp_closed_at': self._dt(camp.closed_at),
            'education_sessions': [{'id': s.id, 'client_uuid': s.client_uuid, 'topic': s.topic,
                                    'educator': s.educator or '', 'start_time': self._dt(s.start_time),
                                    'attendees_count': s.attendees_count}
                                   for s in Env['camp.education.session'].search(dom)],
            'stock': {f['id']: f['stock_qty'] for f in self._formulary(camp)} if can('camp.formulary') else {},
            'followups': [self._followup(f) for f in Env['camp.followup'].search(dom)]
            if can('camp.followup') else [],
            # Diagnoses added by doctors on other phones / in Odoo since the last sync.
            'diagnosis_codes_changed': self._diagnosis_list(since) if since and can('camp.diagnosis.code') else [],
            'rx_templates_changed': self._rx_templates(since) if since and can('camp.rx.template') else [],
            'lab_orders': [self._lab(o) for o in Env['camp.lab.order'].search(dom)] if can('camp.lab.order') else [],
            'eye_exams': [self._eye(e) for e in Env['camp.eye.exam'].search(dom)] if can('camp.eye.exam') else [],
            'glasses': [{'id': g.id, 'kind': g.kind, 'power': g.power, 'quantity': g.quantity}
                        for g in Env['camp.glasses'].search([('camp_id', '=', camp.id)])] if can('camp.glasses') else [],
            'anc_checks': [{'id': a.id, 'client_uuid': a.client_uuid, 'visit_id': a.visit_id.id, 'weeks': a.weeks,
                            'danger_signs': a.danger_signs or '', 'tt_given': a.tt_given, 'notes': a.notes or ''}
                           for a in Env['camp.anc.check'].search(dom)] if can('camp.anc.check') else [],
            'vaccine_records': [{'id': r.id, 'client_uuid': r.client_uuid, 'visit_id': r.visit_id.id,
                                 'vaccine': r.vaccine, 'status': r.status, 'age_months': r.age_months}
                                for r in Env['camp.vaccine.record'].search(dom)] if can('camp.vaccine.record') else [],
            'reminders': [self._reminder(r) for r in Env['camp.reminder'].search(
                dom + ([] if since else [('state', '=', 'to_send')]))] if can('camp.reminder') else [],
            'me_roles': sorted(self._roles()),
            'team': self._team(camp),
        }
        return out

    @api.model
    def queue(self, camp_id, station):
        """Live queue for one station (when the phone is online)."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.queue(camp_id, station)
        states = {
            'triage': ['registered'],
            'doctor': ['registered', 'triaged', 'with_doctor'],
            'pharmacy': ['at_pharmacy'],
            'registration': ['registered'],
        }.get(station)
        if not states:
            raise UserError(_('Unknown station: %s', station))
        visits = self.env['camp.visit'].search([('camp_id', '=', camp.id), ('state', 'in', states)])
        return {'station': station, 'visits': [self._visit(v) for v in visits]}

    @api.model
    def search_patients(self, query, limit=30):
        if not ({'registration', 'lead'} & set(self._roles())):
            raise AccessError(_('Only registration staff can search patients.'))
        if self.env.user.share and not self.env.su:
            return self.sudo().search_patients(query, limit)
        query = (query or '').strip()
        if len(query) < 2:
            return {'patients': []}
        patients = self.env['camp.patient'].search(
            ['|', '|', ('name', 'ilike', query), ('phone', 'ilike', query), ('patient_code', 'ilike', query)],
            limit=min(int(limit or 30), 100))
        self.env['camp.audit.log'].log('search', details=f'"{query[:40]}": {len(patients)} found')
        return {'patients': [self._patient(p) for p in patients]}

    @api.model
    def camp_status(self, camp_id):
        """Used by the close-camp screen."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.camp_status(camp_id)
        visits = self.env['camp.visit'].search([('camp_id', '=', camp.id)])
        counts = {}
        for v in visits:
            counts[v.state] = counts.get(v.state, 0) + 1
        return {'camp': self._camp(camp), 'visits_by_state': counts,
                'waiting': sum(counts.get(s, 0) for s in ('registered', 'triaged', 'with_doctor', 'at_pharmacy'))}

    @api.model
    def calls(self, camp_id, since=None):
        """The call screen's quick check (every few seconds): the latest
        calls only, instead of the whole camp's changes."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.calls(camp_id, since)
        now = fields.Datetime.now()
        start = fields.Datetime.to_datetime(since) if since else now - timedelta(hours=12)
        visits = self.env['camp.visit'].sudo().search(
            [('camp_id', '=', camp.id), ('called_at', '>=', start)], order='called_at desc', limit=20)
        return {
            'server_time': fields.Datetime.to_string(now),
            'calls': [{'client_uuid': v.client_uuid, 'token_no': v.token_no, 'patient_name': v.patient_id.name or '',
                       'called_at': self._dt(v.called_at), 'called_station': v.called_station or '',
                       'called_room': v.called_room or '', 'called_by': v.called_by_id.name or ''}
                      for v in visits],
        }

    @api.model
    def camp_summary(self, camp_id):
        """End-of-day figures for the coordinator to share (e.g. on WhatsApp).
        Counts only: no patient names, phones or notes."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.camp_summary(camp_id)
        if not ({'coordinator', 'lead'} & set(self._roles())):
            raise AccessError(_('Only the coordinator can see the camp summary.'))
        env = self.env(su=True)
        self.env['camp.audit.log'].log('export', camp=camp, details='End-of-day summary')
        visits = env['camp.visit'].search([('camp_id', '=', camp.id)])
        seen = visits.filtered(lambda v: v.state not in ('cancelled', 'booked'))
        patients = seen.patient_id
        consults = env['camp.consultation'].search([('camp_id', '=', camp.id), ('state', '=', 'done')])
        lines = env['camp.prescription.line'].search([('camp_id', '=', camp.id)])
        referrals = env['camp.referral'].search([('camp_id', '=', camp.id)])
        sessions = env['camp.education.session'].search([('camp_id', '=', camp.id)])

        dx_count = {}
        for c in consults:
            for d in c.diagnosis_ids:
                dx_count[d] = dx_count.get(d, 0) + 1
        top_dx = sorted(dx_count.items(), key=lambda kv: (-kv[1], kv[0].code or ''))[:5]

        given = {}
        for line in lines.filtered(lambda l: l.dispensed_qty > 0):
            med = line.substitute_formulary_id or line.formulary_id
            if med:
                given[med] = given.get(med, 0) + line.dispensed_qty
        top_meds = sorted(given.items(), key=lambda kv: -kv[1])[:5]

        by_hospital = {}
        for r in referrals:
            by_hospital[r.hospital_id.name or ''] = by_hospital.get(r.hospital_id.name or '', 0) + 1

        now = fields.Datetime.now()
        team = camp.sudo().team_member_ids
        return {
            'camp': self._camp(camp),
            'generated_at': fields.Datetime.to_string(now),
            'patients': len(seen),
            'seen_by_doctor': len(consults.visit_id),
            'finished': len(seen.filtered(lambda v: v.state in ('done', 'referred'))),
            'still_waiting': len(seen.filtered(lambda v: v.state in ('registered', 'triaged', 'with_doctor', 'at_pharmacy'))),
            'left_early': len(visits.filtered(lambda v: v.state == 'cancelled')),
            'pre_registered_not_come': len(visits.filtered(lambda v: v.state == 'booked')),
            'eye_checks': env['camp.eye.exam'].search_count([('camp_id', '=', camp.id)]),
            'glasses_given': env['camp.eye.exam'].search_count([('camp_id', '=', camp.id), ('glasses_id', '!=', False)]),
            'pregnancy_checks': env['camp.anc.check'].search_count([('camp_id', '=', camp.id)]),
            'high_risk_pregnancies': env['camp.anc.check'].search_count([('camp_id', '=', camp.id),
                                                                         ('high_risk', '=', True)]),
            'vaccines_given': env['camp.vaccine.record'].search_count([('camp_id', '=', camp.id),
                                                                       ('status', '=', 'given')]),
            'children_missing_vaccines': len(env['camp.vaccine.record'].search(
                [('camp_id', '=', camp.id), ('status', '=', 'missed')]).visit_id),
            'lab_tests': self.env['camp.lab.order'].sudo().search_count(
                [('camp_id', '=', camp.id), ('state', '=', 'done')]),
            'new_patients': len(seen.filtered('is_first_visit')),
            'returning': len(seen.filtered(lambda v: not v.is_first_visit)),
            'women': len(patients.filtered(lambda p: p.sex == 'female')),
            'men': len(patients.filtered(lambda p: p.sex == 'male')),
            'children': len(patients.filtered(lambda p: p.age_years and p.age_years < 12)),
            'elderly': len(patients.filtered(lambda p: p.age_years and p.age_years >= 60)),
            'urgent': len(seen.filtered(lambda v: v.priority == 'urgent')),
            'top_diagnoses': [{'code': d.code, 'name': d.name, 'name_ur': d.name_ur or '', 'count': n}
                              for d, n in top_dx],
            'referrals': len(referrals),
            'urgent_referrals': len(referrals.filtered(lambda r: r.urgency == 'urgent')),
            'referral_hospitals': [{'name': k, 'count': v}
                                   for k, v in sorted(by_hospital.items(), key=lambda kv: -kv[1])[:3]],
            'prescriptions': len(consults.filtered('prescription_line_ids')),
            'medicine_units_given': sum(given.values()),
            'top_medicines': [{'name': f.display_name, 'quantity': q} for f, q in top_meds],
            'not_available': len(lines.filtered(lambda l: l.state == 'not_given' or l.shortage_qty > 0)),
            'buy_outside': len(lines.filtered(lambda l: l.state == 'outside')),
            'health_talks': len(sessions),
            'talk_attendees': sum(sessions.mapped('attendees_count')),
            'total_cost': camp.sudo().total_cost,
            'cost_per_patient': camp.sudo().cost_per_patient,
            'currency': camp.sudo().company_id.currency_id.symbol or '',
            'team': len(team),
            'team_checked_in': len(team.filtered(
                lambda m: m.checked_in_at and (not m.checked_out_at or m.checked_out_at < m.checked_in_at))),
        }

    @api.model
    def close_camp(self, camp_id):
        """Coordinator closes the camp from the phone (after everything is synced)."""
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.close_camp(camp_id)
        if self.env.user.share or not ({'coordinator', 'lead'} & set(self._roles())):
            raise AccessError(_('Only the camp coordinator can close the camp.'))
        if camp.state != 'closed':
            camp.action_close()
        return self.camp_status(camp.id)

    # ── Upload ──────────────────────────────────────────────────
    @api.model
    def sync(self, camp_id, payload):
        """Save a batch of records made offline. Each record is saved on its own,
        so one bad record never blocks the rest. Returns, per kind, the server id
        for every client_uuid, plus warnings (e.g. stock shortages)."""
        if not self.env.context.get('camp_no_audit'):
            # One audit line for the whole upload instead of one per record.
            return self.with_context(camp_no_audit=True).sync(camp_id, payload)
        api_env, camp = self._worker(camp_id)
        if api_env is not self:
            return api_env.sync(camp_id, payload)
        payload = payload or {}
        counts = {k: len(v) for k, v in payload.items() if isinstance(v, list) and v}
        if counts:
            self.env['camp.audit.log'].log('upload', camp=camp, details=', '.join(f'{k} {n}' for k, n in counts.items()))
        batch, results = _Batch(self.env), {}
        steps = [
            ('patients', lambda item: self._sync_patient(item)),
            ('visits', lambda item: self._sync_visit(camp, item, batch)),
            ('diagnosis_codes', lambda item: self._sync_diagnosis_code(item)),
            ('rx_templates', lambda item: self._sync_rx_template(item)),
            ('vitals', lambda item: self._sync_vitals(item)),
            ('consultations', lambda item: self._sync_consultation(item, batch)),
            ('lab_orders', lambda item: self._sync_lab_order(item)),
            ('eye_exams', lambda item: self._sync_eye_exam(item)),
            ('photos', lambda item: self._sync_photo(item)),
            ('anc_checks', lambda item: self._sync_anc(item)),
            ('vaccine_records', lambda item: self._sync_vaccine(item)),
            ('prescription_lines', lambda item: self._sync_line(item)),
            ('referrals', lambda item: self._sync_referral(item)),
            ('education_sessions', lambda item: self._sync_session(camp, item)),
            ('checkins', lambda item: self._sync_checkin(camp, item)),
            ('dispenses', lambda item: self._sync_dispense(item, batch)),
            ('visit_actions', lambda item: self._sync_visit_action(item)),
            ('calls', lambda item: self._sync_call(item)),
            ('reminder_sends', lambda item: self._sync_reminder_send(item)),
            ('followup_calls', lambda item: self._sync_followup_call(item)),
            ('stock_counts', lambda item: self._sync_stock_count(camp, item)),
        ]
        for kind, handler in steps:
            items = payload.get(kind) or []
            if not isinstance(items, list):
                raise UserError(_('"%s" must be a list.', kind))
            if len(items) > MAX_ITEMS:
                raise UserError(_('Too many %(kind)s in one upload (max %(max)s).', kind=kind, max=MAX_ITEMS))
            results[kind] = [self._run(kind, handler, item) for item in items]
            if kind == 'prescription_lines':
                self._finish_consultations(batch)
        return {
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
            'results': results,
            'warnings': batch.warnings,
        }

    def _run(self, kind, handler, item):
        uuid = item.get('client_uuid') if isinstance(item, dict) else None
        if not uuid:
            return {'client_uuid': None, 'status': 'error', 'error': _('client_uuid is required')}
        try:
            with self.env.cr.savepoint():
                record, status = handler(item)
                self.env.flush_all()
            return {'client_uuid': uuid, 'id': record.id, 'status': status}
        except (UserError, ValidationError, AccessError, MissingError) as e:
            self.env.invalidate_all()
            return {'client_uuid': uuid, 'status': 'error', 'error': str(e.args[0] if e.args else e)}
        except IntegrityError as e:
            self.env.invalidate_all()
            return {'client_uuid': uuid, 'status': 'error', 'error': _('Conflicts with existing data: %s', e.diag.message_primary or e)}
        except Exception:  # noqa: BLE001 - one bad record must not break the batch
            _logger.exception('Camp sync failed for %s %s', kind, uuid)
            self.env.invalidate_all()
            return {'client_uuid': uuid, 'status': 'error', 'error': _('Server error while saving this record.')}

    # Each handler returns (record, 'created' | 'updated' | 'exists')
    def _upsert(self, model, item, vals, update_vals=None):
        Model = self.env[model]
        existing = Model.search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing:
            upd = vals if update_vals is None else update_vals
            changed = {k: v for k, v in upd.items() if self._differs(existing, k, v)}
            if changed:
                existing.write(changed)
                return existing, 'updated'
            return existing, 'exists'
        return Model.create({**vals, 'client_uuid': item['client_uuid']}), 'created'

    def _sync_patient(self, item):
        self._need('registration')
        vals = self._pick(item, PATIENT_FIELDS)
        if item.get('id'):   # a returning patient edited on the phone
            patient = self.env['camp.patient'].browse(int(item['id'])).exists()
            if not patient:
                raise MissingError(_('Patient %s no longer exists.', item['id']))
            changed = {k: v for k, v in vals.items() if self._differs(patient, k, v)}
            if changed:
                patient.write(changed)
            return patient, 'updated' if changed else 'exists'
        return self._upsert('camp.patient', item, vals)

    def _sync_visit(self, camp, item, batch):
        self._need('registration')
        patient = self._ref('camp.patient', item.get('patient'))
        vals = {'camp_id': camp.id, 'patient_id': patient.id,
                **self._pick(item, ['priority', 'consent_confirmed', 'consent_signature', 'arrived_at', 'pregnant'])}
        booking = item.get('state') == 'booked'
        if booking:
            vals['state'] = 'booked'   # pre-registered before the camp: no token yet
        existing = self.env['camp.visit'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing and existing.state == 'booked' and not booking:
            # The pre-registered patient arrived: token and consent now.
            existing.write(self._pick(item, ['consent_confirmed', 'consent_signature', 'pregnant', 'priority']))
            existing.action_arrive(item.get('token_no'))
            return existing, 'updated'
        if existing:
            upd = self._pick(item, ['priority', 'consent_confirmed', 'consent_signature', 'pregnant'])
            changed = {k: v for k, v in upd.items() if self._differs(existing, k, v)}
            if changed:
                existing.write(changed)
            return existing, 'updated' if changed else 'exists'
        # Same patient already registered at this camp from another phone: reuse it.
        twin = self.env['camp.visit'].search([('camp_id', '=', camp.id), ('patient_id', '=', patient.id)], limit=1)
        if twin and twin.state == 'booked' and not booking:
            twin.write(self._pick(item, ['consent_confirmed', 'consent_signature', 'pregnant', 'priority']))
            twin.action_arrive(item.get('token_no'))
            return twin, 'updated'
        if twin:
            batch.warn('visits', item, _('Patient was already registered at this camp as token %s; the existing visit is used.', twin.token_no))
            return twin, 'exists'
        token = None if booking else item.get('token_no')
        if token:
            taken = self.env['camp.visit'].search_count([('camp_id', '=', camp.id), ('token_no', '=', int(token))])
            if taken:
                batch.warn('visits', item, _('Token %s was already used; a new token was given.', token))
            else:
                vals['token_no'] = int(token)
        visit = self.env['camp.visit'].create({**vals, 'client_uuid': item['client_uuid']})
        return visit, 'created'

    def _sync_vitals(self, item):
        self._need('nurse')
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, VITAL_FIELDS)}
        return self._upsert('camp.vitals', item, vals, update_vals=self._pick(item, VITAL_FIELDS))

    def _sync_consultation(self, item, batch):
        self._need('doctor')
        self._check_doctor_registration()
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, CONSULT_FIELDS)}
        if 'diagnosis_codes' in item:
            vals['diagnosis_ids'] = [(6, 0, self._diagnosis_ids(item['diagnosis_codes']))]
        # The doctor may learn of an allergy or a pregnancy during the visit.
        if 'patient_allergies' in item and (item['patient_allergies'] or '') != (visit.patient_id.allergies or ''):
            visit.patient_id.allergies = item['patient_allergies'] or False
        if 'pregnant' in item and bool(item['pregnant']) != visit.pregnant:
            visit.pregnant = bool(item['pregnant'])
        existing = self.env['camp.consultation'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        update = {k: v for k, v in vals.items() if k != 'visit_id'}
        if existing and existing.state == 'done':
            return self._amend_consultation(existing, item, update)
        record, status = self._upsert('camp.consultation', item, vals, update_vals=update)
        if item.get('finished'):
            batch.to_finish |= record
        return record, status

    def _amend_consultation(self, consult, item, update):
        """A correction to a finished visit (Edit on the doctor's Done list).
        A resend of the same correction is ignored."""
        amend_id = item.get('amend_id')
        reason = (item.get('amend_reason') or '').strip()
        if not amend_id or not reason or consult.last_amend_id == amend_id:
            return consult, 'exists'
        consult._check_can_amend()
        changed = {k: v for k, v in update.items() if k == 'diagnosis_ids' or self._differs(consult, k, v)}
        if 'diagnosis_ids' in changed and set(consult.diagnosis_ids.ids) == set(changed['diagnosis_ids'][0][2]):
            changed.pop('diagnosis_ids')
        consult.write({**changed, 'amend_count': consult.amend_count + 1, 'last_amend_id': amend_id,
                       'last_amend_reason': reason[:200], 'last_amended_at': fields.Datetime.now(),
                       'last_amended_by_id': self.env.user.id})
        fields_txt = ', '.join(sorted(consult._fields[k].string for k in changed)) or _('medicines only')
        consult.message_post(body=_('Corrected after the visit by %(user)s: %(reason)s (%(fields)s)',
                                    user=self.env.user.name, reason=reason, fields=fields_txt))
        self.env['camp.audit.log'].log('change', consult, details=f'Correction: {reason[:120]}')
        if consult.follow_up_needed:
            self.env['camp.followup']._ensure(consult.visit_id, 'doctor',
                                              consult.follow_up_reason or _('Doctor asked for a follow-up call'))
        return consult, 'updated'

    def _sync_diagnosis_code(self, item):
        """A diagnosis a doctor added on the phone (not in the list)."""
        self._need('doctor')
        code = (item.get('code') or '').strip().upper()
        name = (item.get('name') or '').strip()
        if not code or not name:
            raise UserError(_('A new diagnosis needs a code and a name.'))
        Code = self.env['camp.diagnosis.code'].with_context(active_test=False)
        existing = Code.search([('code', '=', code)], limit=1)
        if existing:
            return existing, 'exists'
        return Code.create({'code': code, 'name': name, 'name_ur': item.get('name_ur') or False,
                            'chapter': 'Added by doctors', 'source': 'custom'}), 'created'

    def _sync_rx_template(self, item):
        """A prescription template a doctor saved (or changed / deleted) in Camp Mode."""
        self._need('doctor')
        Template = self.env['camp.rx.template'].with_context(active_test=False)
        existing = Template.search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing and existing.user_id != self.env.user:
            raise UserError(_('Shared templates are changed in Odoo by the medical lead.'))
        if item.get('active') is False:
            if not existing:
                raise MissingError(_('This template is not on the server.'))
            existing.active = False
            return existing, 'updated'
        name = (item.get('name') or '').strip()
        if not name:
            raise UserError(_('A template needs a name.'))
        lines = [(5, 0, 0)]
        for line in item.get('lines') or []:
            vals = {'outside_medicine': (line.get('outside_medicine') or '').strip() or False,
                    'days': int(line.get('days') or 1), 'quantity': float(line.get('quantity') or 0),
                    'instructions_ur': line.get('instructions_ur') or False}
            if line.get('formulary_id'):
                vals['formulary_id'] = self._ref('camp.formulary', line['formulary_id']).id
            if line.get('dose_template_id'):
                vals['dose_template_id'] = self._ref('camp.dose.template', line['dose_template_id']).id
            lines.append((0, 0, vals))
        vals = {'name': name, 'name_ur': item.get('name_ur') or False,
                'advice': item.get('advice') or False, 'advice_ur': item.get('advice_ur') or False,
                'diagnosis_ids': [(6, 0, self._diagnosis_ids(item.get('diagnosis_codes')))],
                'line_ids': lines, 'active': True}
        if existing:
            existing.write(vals)
            return existing, 'updated'
        return Template.create({**vals, 'user_id': self.env.user.id, 'client_uuid': item['client_uuid']}), 'created'

    def _sync_line(self, item):
        self._need('doctor')
        self._check_doctor_registration()
        consult = self._ref('camp.consultation', item.get('consultation'))
        formulary = self._ref('camp.formulary', item.get('formulary_id')) if item.get('formulary_id') \
            else self.env['camp.formulary']
        if not formulary and not (item.get('outside_medicine') or '').strip():
            raise UserError(_('Choose a camp medicine, or write the name of a medicine to buy outside.'))
        vals = {'consultation_id': consult.id, 'formulary_id': formulary.id or False,
                **self._pick(item, LINE_FIELDS)}
        if item.get('dose_template_id'):
            vals['dose_template_id'] = self._ref('camp.dose.template', item['dose_template_id']).id
        existing = self.env['camp.prescription.line'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing and existing.state != 'prescribed':
            return existing, 'exists'   # already handled at the pharmacy
        after_visit = consult.state == 'done'
        if after_visit:
            consult._check_can_amend()
            if formulary and consult.camp_id.state == 'closed':
                raise UserError(_('The camp is closed: write the medicine as "buy outside".'))
        if item.get('removed'):
            # A medicine the doctor took off before the pharmacy gave it.
            if existing:
                existing.unlink()
            return existing, 'updated'
        update = {k: v for k, v in vals.items() if k != 'consultation_id'}
        line, status = self._upsert('camp.prescription.line', item, vals, update_vals=update)
        visit = consult.visit_id
        if after_visit and line.state == 'prescribed' and visit.state in ('done', 'referred'):
            # Added after the visit: the patient goes back to the pharmacy.
            visit.write({'state': 'at_pharmacy', 'pharmacy_reopened': True})
            consult.message_post(body=_('Medicine added after the visit: %s', line.display_name))
        return line, status

    def _finish_consultations(self, batch):
        for consult in batch.to_finish.filtered(lambda c: c.state == 'draft'):
            try:
                with self.env.cr.savepoint():
                    consult.action_finish()
                    self.env.flush_all()
            except (UserError, ValidationError, AccessError) as e:
                batch.warnings.append({'kind': 'consultations', 'client_uuid': consult.client_uuid,
                                       'message': str(e.args[0] if e.args else e)})
        batch.to_finish = self.env['camp.consultation']

    def _sync_referral(self, item):
        self._need('doctor')
        visit = self._ref('camp.visit', item.get('visit')) if item.get('visit') else None
        consult = self._ref('camp.consultation', item.get('consultation')) if item.get('consultation') else None
        if not (visit or consult):
            raise UserError(_('A referral needs a visit or a consultation.'))
        hospital = self.env['res.partner'].browse(int(item.get('hospital_id') or 0)).exists()
        if not hospital:
            raise UserError(_('Choose the hospital for the referral.'))
        vals = {'visit_id': (visit or consult.visit_id).id, 'consultation_id': consult.id if consult else False,
                'hospital_id': hospital.id, **self._pick(item, REFERRAL_FIELDS)}
        update = self._pick(item, REFERRAL_FIELDS)
        return self._upsert('camp.referral', item, vals, update_vals=update)

    def _sync_session(self, camp, item):
        self._need('registration', 'educator')
        vals = {'camp_id': camp.id, **self._pick(item, SESSION_FIELDS)}
        return self._upsert('camp.education.session', item, vals, update_vals=self._pick(item, SESSION_FIELDS))

    def _sync_checkin(self, camp, item):
        """Team check-in / out. Workers can only check themselves in;
        coordinators can check in anyone on the team."""
        member = camp.team_member_ids.filtered(lambda m: m.id == int(item.get('member_id') or 0))
        if not member:
            raise MissingError(_('Team member not found in this camp.'))
        others_allowed = not self.env.user.share and bool({'coordinator', 'lead'} & set(self._roles()))
        if member.user_id != self.env.user and not others_allowed:
            raise AccessError(_('You can only check yourself in.'))
        vals = self._pick(item, ['checked_in_at', 'checked_out_at'])
        member.sudo().write(vals)
        return member, 'updated'

    def _sync_dispense(self, item, batch):
        self._need('pharmacist')
        line = self._ref('camp.prescription.line', item.get('line'))
        if line.state != 'prescribed':
            return line, 'exists'
        if item.get('not_given'):
            line.action_not_given(reason=item.get('reason') or _('Not available'))
            return line, 'updated'
        substitute = self._ref('camp.formulary', item['substitute_formulary_id']).id \
            if item.get('substitute_formulary_id') else None
        quantity = float(item['quantity']) if item.get('quantity') not in (None, '') else None
        line.action_dispense(quantity=quantity, substitute_formulary_id=substitute,
                             reason=item.get('reason'), allow_shortage=True)
        if line.shortage_qty:
            batch.warn('dispenses', item, _('%(qty)s of %(med)s were given offline but were not in camp stock. '
                                            'Check during stock reconciliation.',
                                            qty=line.shortage_qty, med=line.dispensed_product_id.display_name))
        return line, 'updated'

    def _sync_followup_call(self, item):
        self._need('followup')
        followup = self._ref('camp.followup', item.get('followup'))
        followup.log_call(item.get('result'), notes=item.get('notes'), outcome=item.get('outcome'),
                          referral_attended=bool(item.get('referral_attended')))
        return followup, 'updated'

    def _sync_stock_count(self, camp, item):
        existing = self.env['camp.stock.count'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing:
            return existing, 'exists'
        self._need('pharmacist')
        loc = camp.stock_location_id
        lines = []
        for row in item.get('lines') or []:
            formulary = self._ref('camp.formulary', row.get('formulary_id'))
            expected = formulary.product_id.with_context(location=loc.id).qty_available if loc else 0.0
            lines.append((0, 0, {'formulary_id': formulary.id, 'expected_qty': expected,
                                 'counted_qty': float(row.get('counted_qty') or 0)}))
        count = self.env['camp.stock.count'].create({
            'camp_id': camp.id, 'client_uuid': item['client_uuid'],
            'notes': item.get('notes') or False, 'line_ids': lines})
        return count, 'created'

    def _sync_lab_order(self, item):
        """The doctor orders (or cancels) a test; the lab desk records the result."""
        Lab = self.env['camp.lab.order']
        existing = Lab.search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if 'result' in item:
            self._need('nurse')
            if not existing:
                raise MissingError(_('This test was not ordered.'))
            existing.write({'result': (item.get('result') or '').strip() or False, 'abnormal': bool(item.get('abnormal')),
                            'notes': item.get('notes') or existing.notes, 'state': 'done',
                            'done_by_id': self.env.user.id, 'done_at': fields.Datetime.now()})
            return existing, 'updated'
        self._need('doctor')
        if existing:
            if item.get('state') == 'cancelled' and existing.state == 'ordered':
                existing.state = 'cancelled'
                return existing, 'updated'
            return existing, 'exists'
        visit = self._ref('camp.visit', item.get('visit'))
        return Lab.create({'visit_id': visit.id, 'test': item.get('test'), 'test_name': item.get('test_name') or False,
                           'notes': item.get('notes') or False, 'client_uuid': item['client_uuid'],
                           'ordered_by_id': self.env.user.id}), 'created'

    def _sync_eye_exam(self, item):
        self._need('eye')
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, ['va_right', 'va_left', 'near_vision', 'reading_power',
                                                         'findings', 'needs_specialist', 'notes'])}
        if item.get('glasses_id'):
            vals['glasses_id'] = self._ref('camp.glasses', item['glasses_id']).id
        return self._upsert('camp.eye.exam', item, vals, update_vals={k: v for k, v in vals.items() if k != 'visit_id'})

    def _sync_photo(self, item):
        if not ({'doctor', 'nurse', 'lead'} & set(self._roles())):
            raise AccessError(_('Only nurses and doctors take clinical photos.'))
        visit = self._ref('camp.visit', item.get('visit'))
        if not item.get('consent'):
            raise UserError(_('A clinical photo needs the patient\'s consent.'))
        vals = {'visit_id': visit.id, 'image': item.get('image') or False, 'note': item.get('note') or False,
                'consent': True}
        return self._upsert('camp.visit.photo', item, vals, update_vals={'note': vals['note']})

    def _sync_anc(self, item):
        if not ({'doctor', 'nurse', 'lead'} & set(self._roles())):
            raise AccessError(_('Only nurses and doctors record pregnancy checks.'))
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, ['weeks', 'danger_signs', 'tt_given', 'notes'])}
        return self._upsert('camp.anc.check', item, vals, update_vals={k: v for k, v in vals.items() if k != 'visit_id'})

    def _sync_vaccine(self, item):
        if not ({'doctor', 'nurse', 'lead'} & set(self._roles())):
            raise AccessError(_('Only nurses and doctors record vaccines.'))
        visit = self._ref('camp.visit', item.get('visit'))
        existing = self.env['camp.vaccine.record'].search(
            [('visit_id', '=', visit.id), ('vaccine', '=', item.get('vaccine'))], limit=1)
        vals = {'status': item.get('status'), 'age_months': int(item.get('age_months') or 0)}
        if existing:
            existing.write(vals)
            return existing, 'updated'
        return self.env['camp.vaccine.record'].create({'visit_id': visit.id, 'vaccine': item.get('vaccine'), **vals,
                                                       'client_uuid': item['client_uuid']}), 'created'

    def _sync_reminder_send(self, item):
        """A volunteer sent (or skipped) a reminder from their phone."""
        if not ({'followup', 'coordinator', 'lead'} & set(self._roles())):
            raise AccessError(_('Only follow-up volunteers send reminders.'))
        reminder = self._ref('camp.reminder', item.get('reminder'))
        result = item.get('result')
        if result not in ('sent', 'skipped'):
            raise UserError(_('Unknown result: %s', result))
        reminder.mark(result)
        return reminder, 'updated'

    def _sync_call(self, item):
        """A station called a patient ("#23 → Doctor room 2"), for the call screen."""
        station = item.get('station')
        need = {'triage': 'nurse', 'doctor': 'doctor', 'pharmacy': 'pharmacist', 'lab': 'nurse'}.get(station)
        if not need:
            raise UserError(_('Unknown station: %s', station))
        self._need(need)
        visit = self._ref('camp.visit', item.get('visit'))
        when = fields.Datetime.to_datetime(item['called_at']) if item.get('called_at') else fields.Datetime.now()
        if visit.called_at and visit.called_at > when:
            return visit, 'exists'   # a later call already arrived
        visit.sudo().write({'called_at': when, 'called_station': station,
                            'called_room': (item.get('room') or '').strip()[:20] or False,
                            'called_by_id': self.env.user.id})
        return visit, 'updated'

    def _sync_visit_action(self, item):
        self._need('registration')
        visit = self._ref('camp.visit', item.get('visit'))
        action = item.get('action')
        if action == 'send_to_doctor':
            visit.action_send_to_doctor()
        elif action == 'done':
            if visit.state not in ('done', 'referred', 'cancelled'):
                visit.action_done()
        elif action == 'cancel':
            if visit.state not in ('done', 'referred'):
                visit.action_cancel()
        else:
            raise UserError(_('Unknown visit action: %s', action))
        return visit, 'updated'

    # ── Helpers ─────────────────────────────────────────────────
    def _returning_domain(self, camp):
        """Patients from the camp's area — any part of it ("Youhanabad, Lahore"
        matches "Youhanabad") — seen or registered in the last two years."""
        parts = [p.strip() for p in re.split(r'[,/]', camp.area or '') if len(p.strip()) >= 3]
        area = Domain.OR([Domain('area', 'ilike', p) for p in parts]) if parts else Domain.FALSE
        since = fields.Datetime.now() - timedelta(days=365 * RETURNING_YEARS)
        recent = Domain('create_date', '>=', since) | Domain('visit_ids.arrived_at', '>=', since)
        return area & recent

    def _get_camp(self, camp_id):
        camp = self.env['camp.camp'].browse(int(camp_id)).exists()
        if not camp:
            raise MissingError(_('Camp not found.'))
        if self.env.user.share or self.env.su:
            if self.env.user not in camp.sudo().team_member_ids.user_id and not self.env.user._is_superuser() \
                    and 'lead' not in self._roles():
                raise AccessError(_('You are not on the team of this camp.'))
        else:
            camp.check_access('read')
        return camp

    def _ref(self, model, value):
        """A record given as a server id (int) or as {'client_uuid': ...} / a uuid string."""
        Model = self.env[model]
        if isinstance(value, dict):
            value = value.get('id') or value.get('client_uuid')
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            record = Model.browse(int(value)).exists()
        elif isinstance(value, str) and value and 'client_uuid' in Model._fields:
            record = Model.search([('client_uuid', '=', value)], limit=1)
        else:
            record = Model
        if not record:
            raise MissingError(_('%(model)s %(ref)s not found (was it uploaded?).',
                                 model=Model._description, ref=value))
        scope = self.env.context.get('camp_scope')
        if scope and 'camp_id' in Model._fields and record.camp_id.id != scope:
            # Never let a phone touch another camp's records.
            raise MissingError(_('%(model)s %(ref)s is not part of this camp.', model=Model._description, ref=value))
        return record

    def _diagnosis_ids(self, codes):
        ids = []
        Code = self.env['camp.diagnosis.code']
        for c in codes or []:
            rec = Code.browse(c).exists() if isinstance(c, int) else Code.search([('code', '=', c)], limit=1)
            if rec:
                ids.append(rec.id)
        return ids

    @staticmethod
    def _pick(item, names):
        return {k: (v if v != '' else False) for k, v in item.items() if k in names}

    @staticmethod
    def _differs(record, name, value):
        current = record[name]
        field = record._fields[name]
        if field.type == 'many2one':
            return current.id != (int(value) if value else False) and not (not current and not value)
        if field.type == 'many2many':
            ids = value[0][2] if value and isinstance(value[0], (list, tuple)) else (value or [])
            return set(current.ids) != set(ids)
        if field.type in ('date', 'datetime'):
            current = field.to_string(current) if current else False
            value = field.to_string(field.to_date(value) if field.type == 'date' else field.to_datetime(value)) \
                if value else False
        elif field.type == 'binary':
            # Stored as base64 bytes; the phone sends a base64 string.
            current = current.decode() if isinstance(current, bytes) else (current or '')
            return bool(value) and value != current
        return current != value

    @staticmethod
    def _dt(value):
        return fields.Datetime.to_string(value) if value else None

    def _lab(self, o):
        return {'id': o.id, 'client_uuid': o.client_uuid, 'visit_id': o.visit_id.id, 'test': o.test,
                'test_name': o.test_name or '', 'state': o.state, 'result': o.result or '', 'abnormal': o.abnormal,
                'notes': o.notes or '', 'ordered_at': self._dt(o.ordered_at), 'done_at': self._dt(o.done_at)}

    def _eye(self, e):
        return {'id': e.id, 'client_uuid': e.client_uuid, 'visit_id': e.visit_id.id, 'va_right': e.va_right or '',
                'va_left': e.va_left or '', 'near_vision': e.near_vision or '', 'reading_power': e.reading_power,
                'findings': e.findings or '', 'needs_specialist': e.needs_specialist,
                'glasses_id': e.glasses_id.id or None, 'notes': e.notes or ''}

    def _reminder(self, r):
        return {'id': r.id, 'client_uuid': r.client_uuid, 'patient_name': r._who,
                'phone': r.phone or '', 'kind': r.kind, 'message': r.message,
                'due_date': fields.Date.to_string(r.due_date), 'state': r.state}

    def _team(self, camp):
        return [{'id': m.id, 'name': m.name, 'role': m.role, 'user_id': m.user_id.id or None,
                 'checked_in_at': self._dt(m.checked_in_at), 'checked_out_at': self._dt(m.checked_out_at),
                 'shift_start': m.shift_start, 'shift_end': m.shift_end}
                for m in camp.sudo().team_member_ids]

    def _camp(self, c):
        return {'id': c.id, 'name': c.name, 'date_start': fields.Date.to_string(c.date_start),
                'date_end': fields.Date.to_string(c.date_end) if c.date_end else None,
                'site': c.site or '', 'area': c.area or '', 'state': c.state,
                'specialities': c.speciality_ids.mapped('name'),
                'device_purge_days': c.device_purge_days}

    def _formulary(self, camp):
        Line = self.env['camp.prescription.line']
        loc = camp.stock_location_id
        out = []
        for f in self.env['camp.formulary'].search([]):
            qty = Line._allocate_stock(f.product_id, loc, 0)[1] if loc else 0.0
            out.append({'id': f.id, 'name': f.display_name, 'product_id': f.product_id.id,
                        'strength': f.strength or '', 'form': f.form or '',
                        'default_dose_template_id': f.default_dose_template_id.id or None,
                        'default_days': f.default_days, 'instructions_ur': f.instructions_ur or '',
                        'allergy_group': f.allergy_group or '', 'pregnancy_risk': f.pregnancy_risk or '',
                        'mg_per_unit': f.mg_per_unit, 'child_mg_per_kg': f.child_mg_per_kg,
                        'child_max_mg_per_kg_day': f.child_max_mg_per_kg_day,
                        'stock_qty': qty})
        return out

    def _patient(self, p):
        return {'id': p.id, 'client_uuid': p.client_uuid, 'patient_code': p.patient_code, 'name': p.name,
                'date_of_birth': fields.Date.to_string(p.date_of_birth) if p.date_of_birth else None,
                'age_years': p.age_years, 'sex': p.sex, 'phone': p.phone or '', 'area': p.area or '',
                'guardian_name': p.guardian_name or '', 'consent_care': p.consent_care,
                'consent_media': p.consent_media, 'consent_messages': p.consent_messages,
                'allergies': p.allergies or ''}

    def _patients(self, patients, camp=None):
        """Patients for a phone. Doctors also get each patient's last
        prescription from an earlier camp, to repeat it in one tap."""
        rows = [self._patient(p) for p in patients]
        if not rows or not ({'doctor', 'lead'} & set(self._roles())) or not self._may_read('camp.consultation'):
            return rows
        domain = [('visit_id.patient_id', 'in', patients.ids), ('state', '=', 'done')]
        if camp:
            domain.append(('camp_id', '!=', camp.id))
        # Earlier camps' records: the doctor is usually not on those camps'
        # teams, so read them with server rights (only for these patients).
        last = {}
        for c in self.env['camp.consultation'].sudo().search(domain, order='id desc'):
            last.setdefault(c.visit_id.patient_id.id, c)
        history = {}
        vdom = [('patient_id', 'in', patients.ids), ('state', 'not in', ('cancelled', 'booked'))]
        if camp:
            vdom.append(('camp_id', '!=', camp.id))
        for v in self.env['camp.visit'].sudo().search(vdom, order='arrived_at desc'):
            items = history.setdefault(v.patient_id.id, [])
            if len(items) < 6:
                items.append(self._history_item(v))
        for row in rows:
            c = last.get(row['id'])
            if c:
                row['last_rx'] = self._last_rx(c)
            if history.get(row['id']):
                row['history'] = history[row['id']]
        return rows

    def _history_item(self, v):
        """One earlier camp visit: vitals, diagnoses, medicines."""
        vit = v.vitals_ids[:1]
        c = v.consultation_ids.filtered(lambda c: c.state == 'done')[:1]
        when = v.arrived_at or v.create_date
        return {
            'date': fields.Date.to_string(when.date()) if when else None,
            'camp_name': v.camp_id.name or '',
            **({f: vit[f] or None for f in ('bp_systolic', 'bp_diastolic', 'pulse', 'blood_sugar', 'weight',
                                             'hemoglobin', 'temperature')} if vit else {}),
            'diagnoses': c.diagnosis_ids.mapped('display_name') if c else [],
            'medicines': [line.display_name for line in c.prescription_line_ids] if c else [],
            'tests': [o.display_name for o in v.lab_order_ids.filtered(lambda o: o.state == 'done')],
            'referred': bool(v.referral_ids),
        }

    def _last_rx(self, c):
        when = c.visit_id.arrived_at or c.create_date
        return {
            'date': fields.Date.to_string(when.date()) if when else None,
            'camp_name': c.camp_id.name or '',
            'doctor_name': c.doctor_id.name or '',
            'diagnosis_codes': c.diagnosis_ids.mapped('code'),
            'diagnosis_names': c.diagnosis_ids.mapped('display_name'),
            'advice': c.advice or '',
            'advice_ur': c.advice_ur or '',
            'lines': [{'name': line.display_name, 'formulary_id': line.formulary_id.id or None,
                       'outside_medicine': line.outside_medicine or '',
                       'dose_template_id': line.dose_template_id.id or None,
                       'dose_name': line.dose_template_id.name or '', 'days': line.days,
                       'quantity': line.quantity, 'instructions_ur': line.instructions_ur or ''}
                      for line in c.prescription_line_ids],
        }

    def _rx_templates(self, since):
        """Shared templates and this doctor's own. With `since`, only the
        changed ones, archived included (the phone then removes them)."""
        Template = self.env['camp.rx.template']
        domain = Domain('user_id', 'in', [False, self.env.user.id])
        if since:
            when = fields.Datetime.to_datetime(since)
            Template = Template.with_context(active_test=False)
            domain &= Domain('write_date', '>=', when) | Domain('lines_changed_at', '>=', when)
        return [{'id': t.id, 'client_uuid': t.client_uuid, 'name': t.name, 'name_ur': t.name_ur or '',
                 'mine': bool(t.user_id), 'active': t.active, 'sequence': t.sequence,
                 'diagnosis_codes': t.diagnosis_ids.mapped('code'),
                 'advice': t.advice or '', 'advice_ur': t.advice_ur or '',
                 'lines': [{'formulary_id': line.formulary_id.id or None,
                            'outside_medicine': line.outside_medicine or '',
                            'dose_template_id': line.dose_template_id.id or None, 'days': line.days,
                            'quantity': line.quantity, 'instructions_ur': line.instructions_ur or ''}
                           for line in t.line_ids]}
                for t in Template.search(domain)]

    def _visit(self, v):
        return {'id': v.id, 'client_uuid': v.client_uuid, 'patient_id': v.patient_id.id,
                'patient_client_uuid': v.patient_id.client_uuid, 'token_no': v.token_no, 'qr_code': v.qr_code,
                'state': v.state, 'priority': v.priority, 'consent_confirmed': v.consent_confirmed,
                'pregnant': v.pregnant, 'pharmacy_reopened': v.pharmacy_reopened,
                'called_at': self._dt(v.called_at), 'called_station': v.called_station or '',
                'called_room': v.called_room or '', 'called_by': v.called_by_id.name or '',
                'arrived_at': self._dt(v.arrived_at), 'flag_rule_ids': v.flag_rule_ids.ids,
                'is_first_visit': v.is_first_visit, 'write_date': self._dt(v.write_date)}

    def _vitals(self, r):
        return {'id': r.id, 'client_uuid': r.client_uuid, 'visit_id': r.visit_id.id,
                **{f: r[f] for f in VITAL_FIELDS}, 'bmi': r.bmi, 'flag_rule_ids': r.flag_rule_ids.ids}

    def _consultation(self, c):
        return {'id': c.id, 'client_uuid': c.client_uuid, 'visit_id': c.visit_id.id,
                'doctor_id': c.doctor_id.id, 'doctor_name': c.doctor_id.name, 'state': c.state,
                'diagnosis_codes': c.diagnosis_ids.mapped('code'),
                **{f: c[f] or ('' if f not in ('follow_up_needed',) else False) for f in CONSULT_FIELDS},
                'amend_count': c.amend_count, 'last_amend_reason': c.last_amend_reason or ''}

    def _diagnosis_list(self, since):
        """Doctors and pharmacists get the full list (pharmacists print slips);
        other roles only the common camp list, to keep their download small."""
        domain = []
        if not (FULL_DIAGNOSIS_ROLES & set(self._roles())):
            domain.append(('source', '!=', 'icd10'))
        if since:
            domain.append(('write_date', '>=', fields.Datetime.to_datetime(since)))
        rows = self.env['camp.diagnosis.code'].search_read(
            domain, ['code', 'name', 'name_ur', 'favourite', 'chapter'], order='favourite desc, code')
        return [{'id': r['id'], 'code': r['code'], 'name': r['name'], 'name_ur': r['name_ur'] or '',
                 'favourite': r['favourite'], 'chapter': r['chapter'] or ''} for r in rows]

    def _line(self, line):
        return {'id': line.id, 'client_uuid': line.client_uuid, 'consultation_id': line.consultation_id.id,
                'visit_id': line.visit_id.id, 'formulary_id': line.formulary_id.id or None,
                'outside_medicine': line.outside_medicine or '',
                'dose_template_id': line.dose_template_id.id or None, 'days': line.days,
                'quantity': line.quantity, 'instructions_ur': line.instructions_ur or '', 'state': line.state,
                'dispensed_qty': line.dispensed_qty, 'shortage_qty': line.shortage_qty,
                'substitute_formulary_id': line.substitute_formulary_id.id or None,
                'substitution_reason': line.substitution_reason or ''}

    def _followup(self, f):
        return {'id': f.id, 'client_uuid': f.client_uuid, 'visit_id': f.visit_id.id,
                'patient_name': f.patient_id.name, 'patient_phone': f.patient_phone or '',
                'kind': f.kind, 'reason': f.reason, 'state': f.state,
                'due_date': fields.Date.to_string(f.due_date) if f.due_date else None,
                'call_count': f.call_count, 'outcome': f.outcome or '',
                'referral_id': f.referral_id.id or None,
                'hospital_name': f.referral_id.hospital_id.name or ''}

    def _referral(self, r):
        return {'id': r.id, 'client_uuid': r.client_uuid, 'visit_id': r.visit_id.id,
                'consultation_id': r.consultation_id.id or None, 'hospital_id': r.hospital_id.id,
                'hospital_name': r.hospital_id.name, 'department': r.department or '', 'reason': r.reason,
                'urgency': r.urgency, 'status': r.status, 'outcome': r.outcome or '',
                'confirm_url': r.confirm_url or '', 'attended_at': self._dt(r.attended_at)}
