import json
import re
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from odoo.addons.revive_bible_college.models.college_course_content import drive_file_id

MODEL_PATH = 'odoo.addons.revive_bible_college.models.college_course_content'
CLIP = b'\x00\x00\x00\x18ftypmp42' + b'0123456789' * 500


def _drive_response(status=200, content_type='video/mp4', disposition='attachment; filename="Lesson 3.mp4"', body=CLIP):
    response = MagicMock()
    response.status_code = status
    response.headers = {'Content-Type': content_type, 'Content-Disposition': disposition}
    response.iter_content.return_value = [body[i:i + 1000] for i in range(0, len(body), 1000)]
    response.__enter__.return_value = response
    return response


class _VideoSetup:

    @classmethod
    def _make_course(cls):
        cls.program = cls.env['college.program'].create({'name': 'Diploma'})
        cls.term = cls.env['college.term'].create(
            {'name': 'Fall', 'start_date': '2026-09-01', 'end_date': '2026-12-18', 'state': 'active'})
        cls.course = cls.env['college.course'].create({'name': 'Old Testament Survey', 'program_id': cls.program.id})
        cls.module = cls.env['college.course.module'].create({'name': 'The Pentateuch', 'course_id': cls.course.id})
        cls.lesson = cls.env['college.course.content'].create({
            'name': 'The Exodus', 'module_id': cls.module.id, 'content_type': 'video', 'video_source': 'upload',
        })
        cls.youtube = cls.env['college.course.content'].create({
            'name': 'Intro', 'module_id': cls.module.id, 'content_type': 'video',
            'url': 'https://www.youtube.com/watch?v=Qbkj3UrkYn0',
        })
        cls.student = cls.env['college.student'].create(
            {'name': 'Sarah', 'email': 'sarah@example.com', 'program_id': cls.program.id})
        cls.env['college.enrollment'].create({'student_id': cls.student.id, 'course_id': cls.course.id, 'term_id': cls.term.id})

    def _token(self, student):
        code = student._new_signin_code()
        result = self.env['college.student'].app_college_student_activate(student.student_code, code, 'good-password')
        self.assertTrue(result['success'], result)
        return result['session_token']


class TestCollegeVideoModel(_VideoSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()

    def test_drive_links_of_every_common_shape_give_the_file_id(self):
        file_id = '1AbCdEfGhIjKlMnOpQrStUvWx'
        for url in [
            'https://drive.google.com/file/d/%s/view?usp=sharing' % file_id,
            'https://drive.google.com/open?id=%s' % file_id,
            'https://drive.google.com/uc?export=download&id=%s' % file_id,
        ]:
            self.assertEqual(drive_file_id(url), file_id, url)
        self.assertIsNone(drive_file_id('https://www.youtube.com/watch?v=Qbkj3UrkYn0'))
        self.assertIsNone(drive_file_id(''))

    def test_an_uploaded_video_is_stored_and_described(self):
        self.lesson._set_video_file(CLIP, 'exodus.mp4', 'upload')
        self.assertEqual(self.lesson.video_filename, 'exodus.mp4')
        self.assertEqual(self.lesson.video_size, len(CLIP))
        attachment = self.lesson._video_attachment()
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.raw, CLIP)
        self.assertEqual(attachment.mimetype, 'video/mp4')

    def test_uploading_again_replaces_the_old_file_rather_than_piling_up(self):
        self.lesson._set_video_file(CLIP, 'first.mp4', 'upload')
        self.lesson._set_video_file(CLIP + b'more', 'second.mov', 'upload')
        attachment = self.lesson._video_attachment()
        self.assertEqual(len(attachment), 1)
        self.assertEqual(attachment.mimetype, 'video/quicktime')
        self.assertEqual(self.lesson.video_filename, 'second.mov')

    def test_unsupported_empty_and_oversized_files_are_refused(self):
        with self.assertRaises(UserError):
            self.lesson._set_video_file(CLIP, 'notes.pdf', 'upload')
        with self.assertRaises(UserError):
            self.lesson._set_video_file(b'', 'empty.mp4', 'upload')
        with patch(MODEL_PATH + '.MAX_VIDEO_BYTES', 10), self.assertRaises(UserError):
            self.lesson._set_video_file(CLIP, 'big.mp4', 'upload')
        self.assertFalse(self.lesson._video_attachment())
        self.assertEqual(self.lesson.video_size, 0)

    def test_a_shared_drive_video_is_copied_in(self):
        url = 'https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view?usp=sharing'
        with patch(MODEL_PATH + '.requests.get', return_value=_drive_response()) as get:
            self.lesson._import_from_drive(url)
        self.assertEqual(get.call_args.kwargs['params']['id'], '1AbCdEfGhIjKlMnOpQrStUvWx')
        self.assertEqual(self.lesson.video_source, 'drive')
        self.assertEqual(self.lesson.drive_url, url)
        self.assertEqual(self.lesson.video_filename, 'Lesson 3.mp4')
        self.assertEqual(self.lesson._video_attachment().raw, CLIP)

    def test_a_drive_file_named_without_an_extension_still_imports(self):
        response = _drive_response(disposition="attachment; filename*=UTF-8''My%20lesson")
        with patch(MODEL_PATH + '.requests.get', return_value=response):
            self.lesson._import_from_drive('https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWx')
        self.assertEqual(self.lesson.video_filename, 'My lesson.mp4')

    def test_a_drive_file_that_is_not_shared_publicly_explains_why(self):
        with patch(MODEL_PATH + '.requests.get', return_value=_drive_response(content_type='text/html; charset=utf-8')):
            with self.assertRaisesRegex(UserError, 'Anyone with the link'):
                self.lesson._import_from_drive('https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view')
        self.assertFalse(self.lesson._video_attachment())

    def test_a_link_that_is_not_google_drive_is_refused_without_a_request(self):
        with patch(MODEL_PATH + '.requests.get') as get, self.assertRaises(UserError):
            self.lesson._import_from_drive('https://example.com/video.mp4')
        get.assert_not_called()

    def test_the_app_is_told_which_player_to_use(self):
        self.assertFalse(self.youtube._app_video_fields()['has_video_file'])
        self.assertFalse(self.lesson._app_video_fields()['has_video_file'])  # upload chosen, no file yet
        self.lesson._set_video_file(CLIP, 'exodus.mp4', 'upload')
        fields = self.lesson._app_video_fields()
        self.assertTrue(fields['has_video_file'])
        self.assertFalse(fields['has_captions'])
        self.lesson.write({'caption_file': 'V0VCVlRUCgo=', 'caption_filename': 'exodus.vtt'})
        self.assertTrue(self.lesson._app_video_fields()['has_captions'])

    def test_the_student_lesson_list_carries_the_video_fields(self):
        self.lesson._set_video_file(CLIP, 'exodus.mp4', 'upload')
        lessons = {l['id']: l for l in self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons']}
        self.assertTrue(lessons[self.lesson.id]['has_video_file'])
        self.assertEqual(lessons[self.lesson.id]['video_source'], 'upload')
        self.assertFalse(lessons[self.youtube.id]['has_video_file'])
        self.assertEqual(lessons[self.youtube.id]['video_source'], 'youtube')

    def test_removing_the_video_frees_it_from_the_server(self):
        self.lesson._set_video_file(CLIP, 'exodus.mp4', 'upload')
        self.lesson.action_remove_video_file()
        self.assertFalse(self.lesson._video_attachment())
        self.assertEqual(self.lesson.video_size, 0)
        self.assertFalse(self.lesson._app_video_fields()['has_video_file'])

    def test_captions_must_be_a_caption_file(self):
        with self.assertRaises(UserError):
            self.lesson.write({'caption_file': 'aGVsbG8=', 'caption_filename': 'notes.txt'})


@tagged('post_install', '-at_install')
class TestCollegeVideoHttp(_VideoSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()
        cls.lesson._set_video_file(CLIP, 'exodus.mp4', 'upload')
        cls.other_student = cls.env['college.student'].create(
            {'name': 'Ruth', 'email': 'ruth@example.com', 'program_id': cls.program.id})
        cls.staff_user = cls.env['res.users'].create({
            'name': 'College Office', 'login': 'college_office', 'password': 'college_office',
            'group_ids': [(6, 0, [cls.env.ref('revive_bible_college.group_college_staff').id])],
        })
        cls.plain_user = cls.env['res.users'].create({
            'name': 'Someone Else', 'login': 'someone_else', 'password': 'someone_else',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })

    def _video(self, content_id, token=None, headers=None):
        all_headers = dict(headers or {})
        if token:
            all_headers['X-College-Token'] = token
        return self.url_open('/college/video/%d' % content_id, headers=all_headers)

    def test_an_enrolled_student_can_stream_the_whole_video(self):
        response = self._video(self.lesson.id, self._token(self.student))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, CLIP)
        self.assertTrue(response.headers['Content-Type'].startswith('video/mp4'))

    def test_seeking_works_through_range_requests(self):
        response = self._video(self.lesson.id, self._token(self.student), {'Range': 'bytes=100-199'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, CLIP[100:200])
        self.assertEqual(response.headers['Content-Range'], 'bytes 100-199/%d' % len(CLIP))

    def test_no_sign_in_or_another_students_sign_in_gets_nothing(self):
        self.assertEqual(self._video(self.lesson.id).status_code, 404)
        self.assertEqual(self._video(self.lesson.id, 'made-up-token').status_code, 404)
        self.assertEqual(self._video(self.lesson.id, self._token(self.other_student)).status_code, 404)

    def test_a_youtube_lesson_has_nothing_to_stream(self):
        self.assertEqual(self._video(self.youtube.id, self._token(self.student)).status_code, 404)

    def test_captions_stream_only_when_added(self):
        token = self._token(self.student)
        url = '/college/video/%d/captions' % self.lesson.id
        self.assertEqual(self.url_open(url, headers={'X-College-Token': token}).status_code, 404)
        self.lesson.write({'caption_file': 'V0VCVlRUCgowMDowMC4wMDAgLS0+IDAwOjAxLjAwMApIZWxsbwo=',
                           'caption_filename': 'exodus.vtt'})
        response = self.url_open(url, headers={'X-College-Token': token})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'WEBVTT', response.content)

    def _csrf(self, html):
        return re.search(r'data-csrf="([^"]+)"', html).group(1)

    def test_staff_can_upload_a_video_from_the_upload_page(self):
        self.authenticate('college_office', 'college_office')
        page = self.url_open('/college/admin/lesson/%d/video' % self.youtube.id)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Intro', page.text)
        response = self.url_open(
            '/college/admin/lesson/%d/video/upload' % self.youtube.id,
            data={'csrf_token': self._csrf(page.text)},
            files={'video': ('intro.mp4', CLIP, 'video/mp4')},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(json.loads(response.text)['ok'])
        self.youtube.invalidate_recordset()
        self.assertEqual(self.youtube.video_source, 'upload')
        self.assertEqual(self.youtube.video_size, len(CLIP))

    def test_an_upload_of_the_wrong_kind_of_file_explains_why(self):
        self.authenticate('college_office', 'college_office')
        page = self.url_open('/college/admin/lesson/%d/video' % self.lesson.id)
        response = self.url_open(
            '/college/admin/lesson/%d/video/upload' % self.lesson.id,
            data={'csrf_token': self._csrf(page.text)},
            files={'video': ('slides.pptx', b'not a video', 'application/octet-stream')},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('MP4', json.loads(response.text)['error'])

    def test_staff_can_import_from_drive_through_the_page(self):
        self.authenticate('college_office', 'college_office')
        page = self.url_open('/college/admin/lesson/%d/video' % self.lesson.id)
        with patch(MODEL_PATH + '.requests.get', return_value=_drive_response()):
            response = self.url_open(
                '/college/admin/lesson/%d/video/drive' % self.lesson.id,
                data={'csrf_token': self._csrf(page.text),
                      'drive_url': 'https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWx/view'},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.lesson.invalidate_recordset()
        self.assertEqual(self.lesson.video_source, 'drive')

    def test_people_outside_the_college_cannot_open_the_upload_page(self):
        self.authenticate('someone_else', 'someone_else')
        self.assertEqual(self.url_open('/college/admin/lesson/%d/video' % self.lesson.id).status_code, 404)
