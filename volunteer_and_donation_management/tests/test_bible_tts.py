import base64
from unittest.mock import MagicMock, patch

from odoo.tests import TransactionCase, tagged

MP3 = base64.b64encode(b'ID3-fake-mp3').decode()


def ok_response():
    response = MagicMock(status_code=200)
    response.json.return_value = {'audioContent': MP3}
    return response


@tagged('post_install', '-at_install')
class TestBibleTts(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Clip = self.env['revive.tts.clip']
        self.params = self.env['ir.config_parameter'].sudo()
        self.params.set_param('revive.google_tts_api_key', 'test-key')

    def test_not_configured_without_key(self):
        self.params.set_param('revive.google_tts_api_key', '')
        self.assertEqual(self.Clip.app_bible_tts('In the beginning')['error'], 'not_configured')

    def test_fetches_once_then_reuses_the_saved_clip(self):
        with patch('odoo.addons.volunteer_and_donation_management.models.bible_tts.requests.post',
                   return_value=ok_response()) as post:
            first = self.Clip.app_bible_tts('ابتدا میں خدا نے', language='ur', female=False, rate=0.9)
            second = self.Clip.app_bible_tts('ابتدا میں   خدا نے', language='ur-PK', female=False, rate=0.9)
        self.assertTrue(first['success'])
        self.assertEqual(first['audio'], MP3)
        self.assertEqual(second['audio'], MP3)
        self.assertEqual(post.call_count, 1)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['voice'], {'languageCode': 'ur-IN', 'name': 'ur-IN-Wavenet-B'})
        self.assertEqual(body['audioConfig']['speakingRate'], 0.9)

    def test_voice_can_be_changed_and_daily_limit_applies(self):
        self.params.set_param('revive.tts_voice_en_female', 'en-US-Neural2-C')
        self.params.set_param('revive.tts_daily_char_limit', '10')
        with patch('odoo.addons.volunteer_and_donation_management.models.bible_tts.requests.post',
                   return_value=ok_response()) as post:
            self.assertTrue(self.Clip.app_bible_tts('Short.', language='en', female=True)['success'])
            over = self.Clip.app_bible_tts('This one is far too long.', language='en', female=True)
        self.assertEqual(post.call_args.kwargs['json']['voice']['name'], 'en-US-Neural2-C')
        self.assertEqual(over['error'], 'daily_limit')

    def test_google_refusal_is_reported_not_raised(self):
        with patch('odoo.addons.volunteer_and_donation_management.models.bible_tts.requests.post',
                   return_value=MagicMock(status_code=403, text='API key not valid')):
            self.assertEqual(self.Clip.app_bible_tts('Hello')['error'], 'unavailable')
