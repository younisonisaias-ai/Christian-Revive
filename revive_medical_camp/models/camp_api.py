"""Server side of Camp Mode: what a camp phone downloads before the camp, and
how the records it saved offline are uploaded.

Everything here runs as the signed-in camp worker, so the normal access
rights and record rules decide what they can read and write. Uploads are
idempotent: each record carries the phone's own id (client_uuid); sending
the same batch again updates or skips, it never duplicates.
"""
import logging

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
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
MAX_ITEMS = 500           # per kind, per upload
RETURNING_PATIENTS = 3000  # patients from the camp's area sent to phones

PATIENT_FIELDS = ['name', 'date_of_birth', 'age_years', 'sex', 'phone', 'area', 'guardian_name',
                  'consent_care', 'consent_media', 'consent_messages']
VITAL_FIELDS = ['bp_systolic', 'bp_diastolic', 'pulse', 'temperature', 'spo2', 'weight', 'height',
                'blood_sugar', 'hemoglobin', 'urine_dipstick', 'vision_left', 'vision_right', 'notes']
CONSULT_FIELDS = ['complaint', 'history', 'examination', 'advice', 'advice_ur',
                  'follow_up_needed', 'follow_up_reason']
LINE_FIELDS = ['days', 'quantity', 'instructions_ur']
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
        user = user or self.env.user
        return [role for role, xmlid in ROLE_GROUPS if user.has_group(xmlid)]

    @api.model
    def me(self):
        user = self.env.user
        camps = self.env['camp.camp'].search([('state', '!=', 'closed')], order='date_start')
        return {
            'user': {
                'id': user.id, 'name': user.name, 'login': user.login,
                'roles': self._roles(user),
                'has_pmdc_number': bool(user.camp_pmdc_number),
            },
            'camps': [self._camp(c) for c in camps],
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
        }

    # ── Download ────────────────────────────────────────────────
    @api.model
    def bootstrap(self, camp_id, reserve_tokens=0):
        """Everything a phone needs to run its station offline."""
        camp = self._get_camp(camp_id)
        Env = self.env
        can = lambda model: Env[model].has_access('read')  # noqa: E731
        data = {
            'server_time': fields.Datetime.to_string(fields.Datetime.now()),
            'camp': self._camp(camp),
            'me': {'id': Env.user.id, 'name': Env.user.name, 'roles': self._roles(),
                   'has_pmdc_number': bool(Env.user.camp_pmdc_number),
                   'team_member_id': camp.team_member_ids.filtered(lambda m: m.user_id == Env.user)[:1].id or None},
            'team': [{'id': m.id, 'name': m.name, 'role': m.role, 'user_id': m.user_id.id or None,
                      'checked_in_at': self._dt(m.checked_in_at), 'checked_out_at': self._dt(m.checked_out_at)}
                     for m in camp.team_member_ids],
            'flag_rules': [{'id': r.id, 'name': r.name, 'name_ur': r.name_ur or '', 'measure': r.measure,
                            'operator': r.operator, 'value': r.value, 'priority': r.priority}
                           for r in Env['camp.flag.rule'].search([])] if can('camp.flag.rule') else [],
            'dose_templates': [{'id': d.id, 'name': d.name, 'name_ur': d.name_ur or '',
                                'doses_per_day': d.doses_per_day, 'as_needed': d.as_needed}
                               for d in Env['camp.dose.template'].search([])] if can('camp.dose.template') else [],
            'diagnosis_codes': [{'id': d.id, 'code': d.code, 'name': d.name, 'name_ur': d.name_ur or '',
                                 'favourite': d.favourite, 'chapter': d.chapter or ''}
                                for d in Env['camp.diagnosis.code'].search([])] if can('camp.diagnosis.code') else [],
            'formulary': self._formulary(camp) if can('camp.formulary') else [],
            'hospitals': [{'id': p.id, 'name': p.name, 'city': p.city or ''}
                          for p in Env['res.partner'].sudo().search([('camp_is_hospital', '=', True)])],
            'patients': [],
            'token_block': None,
        }
        if can('camp.patient'):
            area_patients = Env['camp.patient'].search(
                [('area', '=ilike', camp.area)], limit=RETURNING_PATIENTS, order='id desc') if camp.area else Env['camp.patient']
            camp_patients = Env['camp.visit'].search([('camp_id', '=', camp.id)]).patient_id
            data['patients'] = [self._patient(p) for p in (camp_patients | area_patients)]
        if reserve_tokens and 'registration' in self._roles():
            data['token_block'] = camp.sudo()._reserve_tokens(reserve_tokens)
        data.update(self.changes(camp.id, since=None))   # also sets server_time
        return data

    @api.model
    def changes(self, camp_id, since=None):
        """Records of this camp changed since `since` (UTC string), so each phone
        sees what the other stations did."""
        camp = self._get_camp(camp_id)
        Env = self.env
        now = fields.Datetime.now()
        dom = [('camp_id', '=', camp.id)]
        if since:
            dom.append(('write_date', '>=', fields.Datetime.to_datetime(since)))
        can = lambda model: Env[model].has_access('read')  # noqa: E731
        visits = Env['camp.visit'].search(dom) if can('camp.visit') else Env['camp.visit']
        out = {
            'server_time': fields.Datetime.to_string(now),
            'visits': [self._visit(v) for v in visits],
            'changed_patients': [self._patient(p) for p in visits.patient_id] if since else [],
            'vitals': [self._vitals(r) for r in Env['camp.vitals'].search(dom)] if can('camp.vitals') else [],
            'consultations': [self._consultation(c) for c in Env['camp.consultation'].search(dom)]
            if can('camp.consultation') else [],
            'prescription_lines': [self._line(line) for line in Env['camp.prescription.line'].search(dom)]
            if can('camp.prescription.line') else [],
            'referrals': [self._referral(r) for r in Env['camp.referral'].search(dom)]
            if can('camp.referral') else [],
            'education_sessions': [{'id': s.id, 'client_uuid': s.client_uuid, 'topic': s.topic,
                                    'educator': s.educator or '', 'start_time': self._dt(s.start_time),
                                    'attendees_count': s.attendees_count}
                                   for s in Env['camp.education.session'].search(dom)],
            'stock': {f['id']: f['stock_qty'] for f in self._formulary(camp)} if can('camp.formulary') else {},
        }
        return out

    @api.model
    def queue(self, camp_id, station):
        """Live queue for one station (when the phone is online)."""
        camp = self._get_camp(camp_id)
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
        query = (query or '').strip()
        if len(query) < 2:
            return {'patients': []}
        patients = self.env['camp.patient'].search(
            ['|', '|', ('name', 'ilike', query), ('phone', 'ilike', query), ('patient_code', 'ilike', query)],
            limit=min(int(limit or 30), 100))
        return {'patients': [self._patient(p) for p in patients]}

    @api.model
    def camp_status(self, camp_id):
        """Used by the close-camp screen."""
        camp = self._get_camp(camp_id)
        visits = self.env['camp.visit'].search([('camp_id', '=', camp.id)])
        counts = {}
        for v in visits:
            counts[v.state] = counts.get(v.state, 0) + 1
        return {'camp': self._camp(camp), 'visits_by_state': counts,
                'waiting': sum(counts.get(s, 0) for s in ('registered', 'triaged', 'with_doctor', 'at_pharmacy'))}

    # ── Upload ──────────────────────────────────────────────────
    @api.model
    def sync(self, camp_id, payload):
        """Save a batch of records made offline. Each record is saved on its own,
        so one bad record never blocks the rest. Returns, per kind, the server id
        for every client_uuid, plus warnings (e.g. stock shortages)."""
        camp = self._get_camp(camp_id)
        payload = payload or {}
        batch, results = _Batch(self.env), {}
        steps = [
            ('patients', lambda item: self._sync_patient(item)),
            ('visits', lambda item: self._sync_visit(camp, item, batch)),
            ('vitals', lambda item: self._sync_vitals(item)),
            ('consultations', lambda item: self._sync_consultation(item, batch)),
            ('prescription_lines', lambda item: self._sync_line(item)),
            ('referrals', lambda item: self._sync_referral(item)),
            ('education_sessions', lambda item: self._sync_session(camp, item)),
            ('checkins', lambda item: self._sync_checkin(camp, item)),
            ('dispenses', lambda item: self._sync_dispense(item, batch)),
            ('visit_actions', lambda item: self._sync_visit_action(item)),
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
        patient = self._ref('camp.patient', item.get('patient'))
        vals = {'camp_id': camp.id, 'patient_id': patient.id,
                **self._pick(item, ['priority', 'consent_confirmed', 'consent_signature', 'arrived_at'])}
        existing = self.env['camp.visit'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing:
            upd = self._pick(item, ['priority', 'consent_confirmed', 'consent_signature'])
            changed = {k: v for k, v in upd.items() if self._differs(existing, k, v)}
            if changed:
                existing.write(changed)
            return existing, 'updated' if changed else 'exists'
        # Same patient already registered at this camp from another phone: reuse it.
        twin = self.env['camp.visit'].search([('camp_id', '=', camp.id), ('patient_id', '=', patient.id)], limit=1)
        if twin:
            batch.warn('visits', item, _('Patient was already registered at this camp as token %s; the existing visit is used.', twin.token_no))
            return twin, 'exists'
        token = item.get('token_no')
        if token:
            taken = self.env['camp.visit'].search_count([('camp_id', '=', camp.id), ('token_no', '=', int(token))])
            if taken:
                batch.warn('visits', item, _('Token %s was already used; a new token was given.', token))
            else:
                vals['token_no'] = int(token)
        visit = self.env['camp.visit'].create({**vals, 'client_uuid': item['client_uuid']})
        return visit, 'created'

    def _sync_vitals(self, item):
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, VITAL_FIELDS)}
        return self._upsert('camp.vitals', item, vals, update_vals=self._pick(item, VITAL_FIELDS))

    def _sync_consultation(self, item, batch):
        visit = self._ref('camp.visit', item.get('visit'))
        vals = {'visit_id': visit.id, **self._pick(item, CONSULT_FIELDS)}
        if 'diagnosis_codes' in item:
            vals['diagnosis_ids'] = [(6, 0, self._diagnosis_ids(item['diagnosis_codes']))]
        existing = self.env['camp.consultation'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing and existing.state == 'done':
            return existing, 'exists'
        update = {k: v for k, v in vals.items() if k != 'visit_id'}
        record, status = self._upsert('camp.consultation', item, vals, update_vals=update)
        if item.get('finished'):
            batch.to_finish |= record
        return record, status

    def _sync_line(self, item):
        consult = self._ref('camp.consultation', item.get('consultation'))
        formulary = self._ref('camp.formulary', item.get('formulary_id'))
        vals = {'consultation_id': consult.id, 'formulary_id': formulary.id, **self._pick(item, LINE_FIELDS)}
        if item.get('dose_template_id'):
            vals['dose_template_id'] = self._ref('camp.dose.template', item['dose_template_id']).id
        existing = self.env['camp.prescription.line'].search([('client_uuid', '=', item['client_uuid'])], limit=1)
        if existing and existing.state != 'prescribed':
            return existing, 'exists'   # already handled at the pharmacy
        update = {k: v for k, v in vals.items() if k != 'consultation_id'}
        return self._upsert('camp.prescription.line', item, vals, update_vals=update)

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
        vals = {'camp_id': camp.id, **self._pick(item, SESSION_FIELDS)}
        return self._upsert('camp.education.session', item, vals, update_vals=self._pick(item, SESSION_FIELDS))

    def _sync_checkin(self, camp, item):
        """Team check-in / out. Workers can only check themselves in;
        coordinators can check in anyone on the team."""
        member = camp.team_member_ids.filtered(lambda m: m.id == int(item.get('member_id') or 0))
        if not member:
            raise MissingError(_('Team member not found in this camp.'))
        if member.user_id != self.env.user and 'coordinator' not in self._roles():
            raise AccessError(_('You can only check yourself in.'))
        vals = self._pick(item, ['checked_in_at', 'checked_out_at'])
        member.sudo().write(vals)
        return member, 'updated'

    def _sync_dispense(self, item, batch):
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

    def _sync_visit_action(self, item):
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
    def _get_camp(self, camp_id):
        camp = self.env['camp.camp'].browse(int(camp_id)).exists()
        if not camp:
            raise MissingError(_('Camp not found.'))
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
            return bool(value) and value != current
        return current != value

    @staticmethod
    def _dt(value):
        return fields.Datetime.to_string(value) if value else None

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
                        'stock_qty': qty})
        return out

    def _patient(self, p):
        return {'id': p.id, 'client_uuid': p.client_uuid, 'patient_code': p.patient_code, 'name': p.name,
                'date_of_birth': fields.Date.to_string(p.date_of_birth) if p.date_of_birth else None,
                'age_years': p.age_years, 'sex': p.sex, 'phone': p.phone or '', 'area': p.area or '',
                'guardian_name': p.guardian_name or '', 'consent_care': p.consent_care,
                'consent_media': p.consent_media, 'consent_messages': p.consent_messages}

    def _visit(self, v):
        return {'id': v.id, 'client_uuid': v.client_uuid, 'patient_id': v.patient_id.id,
                'patient_client_uuid': v.patient_id.client_uuid, 'token_no': v.token_no, 'qr_code': v.qr_code,
                'state': v.state, 'priority': v.priority, 'consent_confirmed': v.consent_confirmed,
                'arrived_at': self._dt(v.arrived_at), 'flag_rule_ids': v.flag_rule_ids.ids,
                'is_first_visit': v.is_first_visit, 'write_date': self._dt(v.write_date)}

    def _vitals(self, r):
        return {'id': r.id, 'client_uuid': r.client_uuid, 'visit_id': r.visit_id.id,
                **{f: r[f] for f in VITAL_FIELDS}, 'bmi': r.bmi, 'flag_rule_ids': r.flag_rule_ids.ids}

    def _consultation(self, c):
        return {'id': c.id, 'client_uuid': c.client_uuid, 'visit_id': c.visit_id.id,
                'doctor_id': c.doctor_id.id, 'doctor_name': c.doctor_id.name, 'state': c.state,
                'diagnosis_codes': c.diagnosis_ids.mapped('code'),
                **{f: c[f] or ('' if f not in ('follow_up_needed',) else False) for f in CONSULT_FIELDS}}

    def _line(self, line):
        return {'id': line.id, 'client_uuid': line.client_uuid, 'consultation_id': line.consultation_id.id,
                'visit_id': line.visit_id.id, 'formulary_id': line.formulary_id.id,
                'dose_template_id': line.dose_template_id.id or None, 'days': line.days,
                'quantity': line.quantity, 'instructions_ur': line.instructions_ur or '', 'state': line.state,
                'dispensed_qty': line.dispensed_qty, 'shortage_qty': line.shortage_qty,
                'substitute_formulary_id': line.substitute_formulary_id.id or None,
                'substitution_reason': line.substitution_reason or ''}

    def _referral(self, r):
        return {'id': r.id, 'client_uuid': r.client_uuid, 'visit_id': r.visit_id.id,
                'consultation_id': r.consultation_id.id or None, 'hospital_id': r.hospital_id.id,
                'hospital_name': r.hospital_id.name, 'department': r.department or '', 'reason': r.reason,
                'urgency': r.urgency, 'status': r.status, 'outcome': r.outcome or ''}
