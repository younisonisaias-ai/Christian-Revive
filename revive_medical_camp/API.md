# Camp Mode API (`/api/camp/…`)

JSON over HTTPS. Every camp worker signs in with their **own** login; shared
logins are not supported. The key returned by `login` works only for this API
(scope `revive_camp`), expires after 30 days and is deleted by `logout`.

Send it on every other call: `Authorization: Bearer <token>`.

Errors always look like `{"error": {"code": "...", "message": "..."}}`:
`400 bad_request`, `401 unauthorized` (sign in again), `403 forbidden`,
`404 not_found`, `500 server_error`.

## Sign in / out

| Call | Body / query | Returns |
|---|---|---|
| `POST /api/camp/login` | `{login, password, device_name}` | `{token, expires_in_days, user: {id, name, roles[], has_pmdc_number}, camps[], server_time}` |
| `POST /api/camp/logout` | – | `{ok: true}` |
| `GET /api/camp/me` | – | same as login, without the token |

Roles: `lead`, `coordinator`, `doctor`, `nurse`, `pharmacist`, `registration`, `followup`.
A login without any camp role gets `403`. Logins with two-step verification get `403 mfa_not_supported`.

## Before the camp (download)

`GET /api/camp/<camp_id>/bootstrap?reserve_tokens=50`

Returns everything a station needs offline: `camp`, `me`, `team`,
`flag_rules`, `dose_templates`, `diagnosis_codes`, `formulary` (with
`stock_qty` from the camp location, expired batches excluded), `hospitals`,
`patients` (this camp's and the area's returning patients), `visits`,
`vitals`, `consultations`, `prescription_lines`, `referrals`,
`education_sessions`, `stock`, `server_time`.

Sections the worker's role cannot read come back empty.

`token_block: {from, to}` (registration only): token numbers reserved for
this phone. Use them in order when registering offline, so two phones never
give the same token. Ask for more with `POST /api/camp/<id>/tokens {count}`.

## During the camp

| Call | Purpose |
|---|---|
| `POST /api/camp/<id>/sync` | upload records saved offline (below) |
| `GET /api/camp/<id>/changes?since=<server_time>` | what other stations did since the last call; store the returned `server_time` for the next call |
| `GET /api/camp/<id>/queue/<station>` | live queue: `registration`, `triage`, `doctor`, `pharmacy` |
| `GET /api/camp/patients?q=<name/phone/code>` | search returning patients online |
| `GET /api/camp/<id>/status` | visits by state + `waiting` count (close-camp screen) |

## Upload (`sync`)

Body: any of these lists (max 500 items each). Every item needs a
`client_uuid` made on the phone. Links to other records use either the server
`id` (int) or that record's `client_uuid` (string), so a whole offline chain
can go up in one call. They are saved in this order:

| Kind | Fields |
|---|---|
| `patients` | `name, sex, age_years, date_of_birth, phone, area, guardian_name, consent_care, consent_media, consent_messages` (send `id` to update a returning patient) |
| `visits` | `patient, token_no, priority, consent_confirmed, consent_signature (base64 PNG), arrived_at` |
| `vitals` | `visit, bp_systolic, bp_diastolic, pulse, temperature, spo2, weight, height, blood_sugar, hemoglobin, urine_dipstick, vision_left, vision_right, notes` |
| `consultations` | `visit, complaint, history, examination, diagnosis_codes ["I10", …], advice, advice_ur, follow_up_needed, follow_up_reason, finished` |
| `prescription_lines` | `consultation, formulary_id, dose_template_id, days, quantity, instructions_ur` |
| `referrals` | `visit` or `consultation`, `hospital_id, department, reason, urgency, status, outcome` |
| `education_sessions` | `topic, educator, start_time, attendees_count` |
| `checkins` | `member_id, checked_in_at, checked_out_at` (yourself; coordinators anyone) |
| `dispenses` | `line, quantity, substitute_formulary_id, reason, not_given` |
| `visit_actions` | `visit, action: send_to_doctor / done / cancel` |

Reply:

```json
{
  "server_time": "2026-10-10 09:15:00",
  "results": {"patients": [{"client_uuid": "…", "id": 41, "status": "created"}], "visits": [...]},
  "warnings": [{"kind": "visits", "client_uuid": "…", "message": "Token 7 was already used; a new token was given."}]
}
```

`status` is `created`, `updated`, `exists` (already uploaded, nothing changed)
or `error` (with `error` text; the rest of the batch is still saved). Sending
the same batch twice is safe. Keep a record in the phone's queue until it
comes back as anything but `error`; show errors to the user.

Rules the server enforces (the app should prevent them earlier):
care consent before vitals; only doctors with a PMDC number save
consultations; only formulary medicines; expired batches are never given.
Medicines given offline that the camp stock cannot cover are saved and
reported as a warning for stock reconciliation.
