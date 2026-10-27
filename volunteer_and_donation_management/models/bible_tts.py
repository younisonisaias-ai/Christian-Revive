"""Bible and book read-aloud voices, from Google Cloud Text-to-Speech.

The app sends a verse (or paragraph), the language and male/female; the ERP
asks Google for the MP3 with the church's own API key (kept here, never in
the app) and keeps every clip, so each verse is paid for once. A daily
character limit protects against surprise bills.

Settings (Settings → Technical → System Parameters):
  revive.google_tts_api_key        the Google Cloud API key (required)
  revive.tts_daily_char_limit      new characters per day, default 200000
  revive.tts_voice_<ur|en>_<male|female>   voice names (see VOICES)
"""
import base64
import hashlib
import logging

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

API_URL = 'https://texttospeech.googleapis.com/v1/text:synthesize'
MAX_CHARS = 2500

# Google voices, changeable per church from System Parameters.
VOICES = {
    ('ur', False): 'ur-IN-Wavenet-B',
    ('ur', True): 'ur-IN-Wavenet-A',
    ('en', False): 'en-US-Neural2-D',
    ('en', True): 'en-US-Neural2-F',
}


class ReviveTtsClip(models.Model):
    _name = 'revive.tts.clip'
    _description = 'Read-aloud audio clip'
    _order = 'id desc'

    key = fields.Char(required=True, index=True)
    voice = fields.Char()
    chars = fields.Integer()
    audio = fields.Binary(attachment=True)

    _key_uniq = models.Constraint('unique(key)', 'One clip per text, voice and speed.')

    @api.model
    def _voice(self, language, female):
        param = 'revive.tts_voice_%s_%s' % (language, 'female' if female else 'male')
        return (self.env['ir.config_parameter'].sudo().get_param(param) or '').strip() \
            or VOICES[(language, bool(female))]

    @api.model
    def _chars_today(self):
        start = fields.Datetime.to_string(fields.Datetime.now().replace(hour=0, minute=0, second=0))
        groups = self.sudo()._read_group([('create_date', '>=', start)], [], ['chars:sum'])
        return (groups[0][0] if groups else 0) or 0

    @api.model
    def app_bible_tts(self, text, language='en', female=False, rate=1.0):
        """MP3 (base64) of [text] read aloud. rate: 0.5–2.0 (1.0 = normal)."""
        text = ' '.join(str(text or '').split())
        language = 'ur' if str(language or '').lower().startswith('ur') else 'en'
        try:
            rate = round(min(2.0, max(0.5, float(rate or 1.0))), 2)
        except (TypeError, ValueError):
            rate = 1.0
        if not text:
            return {'success': False, 'error': 'empty'}
        if len(text) > MAX_CHARS:
            return {'success': False, 'error': 'too_long'}
        voice = self._voice(language, female)
        key = hashlib.sha256(('%s|%s|%s' % (voice, rate, text)).encode('utf-8')).hexdigest()
        clip = self.sudo().search([('key', '=', key)], limit=1)
        if clip and clip.audio:
            return {'success': True, 'audio': clip.audio.decode() if isinstance(clip.audio, bytes) else clip.audio}

        params = self.env['ir.config_parameter'].sudo()
        api_key = (params.get_param('revive.google_tts_api_key') or '').strip()
        if not api_key:
            return {'success': False, 'error': 'not_configured'}
        try:
            limit = int(params.get_param('revive.tts_daily_char_limit') or 200000)
        except ValueError:
            limit = 200000
        if self._chars_today() + len(text) > limit:
            return {'success': False, 'error': 'daily_limit'}

        language_code = '-'.join(voice.split('-')[:2])
        try:
            response = requests.post(API_URL, params={'key': api_key}, timeout=20, json={
                'input': {'text': text},
                'voice': {'languageCode': language_code, 'name': voice},
                'audioConfig': {'audioEncoding': 'MP3', 'speakingRate': rate},
            })
        except requests.RequestException as exc:
            _logger.warning('Read-aloud request failed: %s', exc)
            return {'success': False, 'error': 'unavailable'}
        if response.status_code != 200:
            _logger.warning('Read-aloud refused (%s): %s', response.status_code, response.text[:300])
            return {'success': False, 'error': 'unavailable'}
        audio = (response.json() or {}).get('audioContent')
        if not audio:
            return {'success': False, 'error': 'unavailable'}
        # Another phone may have saved the same verse meanwhile.
        if not self.sudo().search_count([('key', '=', key)]):
            self.sudo().create({'key': key, 'voice': voice, 'chars': len(text), 'audio': audio})
        return {'success': True, 'audio': audio}
