import base64

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.revive_bible_college.models.college_course_content import parse_chapters

from .test_college_video import _VideoSetup

VTT = b'WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nIn the beginning\n'
PDF = b'%PDF-1.4\n% study guide\n'


class TestCollegeChapters(TransactionCase):

    def test_chapters_read_like_a_youtube_description(self):
        chapters, unreadable = parse_chapters(
            '0:00 Introduction\n'
            '\n'
            '12:10 - The Passover\n'
            '4:30 Moses and Pharaoh\n'
            '1:02:05 | Closing prayer\n'
        )
        self.assertEqual(chapters, [
            {'seconds': 0, 'title': 'Introduction'},
            {'seconds': 270, 'title': 'Moses and Pharaoh'},
            {'seconds': 730, 'title': 'The Passover'},
            {'seconds': 3725, 'title': 'Closing prayer'},
        ])
        self.assertEqual(unreadable, [])

    def test_lines_that_are_not_chapters_are_listed_back_not_refused(self):
        chapters, unreadable = parse_chapters('0:00 Introduction\nMoses at 4:30\n4:75 Bad seconds\n9:00\n')
        self.assertEqual(chapters, [{'seconds': 0, 'title': 'Introduction'}])
        self.assertEqual(unreadable, ['Moses at 4:30', '4:75 Bad seconds', '9:00'])
        self.assertEqual(parse_chapters(False), ([], []))


class TestCollegeStudyTools(_VideoSetup, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()
        cls.Note = cls.env['college.lesson.note']

    def test_a_lesson_sends_its_chapters_and_study_guide_to_the_app(self):
        self.youtube.write({
            'chapters_text': '0:00 Introduction\n4:30 Moses and Pharaoh\nnot a chapter',
            'study_guide': base64.b64encode(PDF), 'study_guide_filename': 'exodus.pdf',
        })
        self.assertEqual(self.youtube.chapters_unreadable, '"not a chapter"')
        lessons = {l['id']: l for l in self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons']}
        lesson = lessons[self.youtube.id]
        self.assertEqual(lesson['chapters'], [
            {'seconds': 0, 'title': 'Introduction'}, {'seconds': 270, 'title': 'Moses and Pharaoh'}])
        self.assertTrue(lesson['has_study_guide'])
        self.assertFalse(lessons[self.lesson.id]['has_study_guide'])

    def test_a_youtube_lesson_can_have_a_transcript(self):
        self.assertFalse(self.youtube._app_video_fields()['has_captions'])
        self.youtube.write({'caption_file': base64.b64encode(VTT), 'caption_filename': 'intro.vtt'})
        fields = self.youtube._app_video_fields()
        self.assertTrue(fields['has_captions'])
        self.assertFalse(fields['has_video_file'])

    def test_extras_are_only_sent_for_video_lessons(self):
        text = self.env['college.course.content'].create({
            'name': 'Reading', 'module_id': self.module.id, 'content_type': 'text', 'chapters_text': '0:00 Hi',
        })
        fields = text._app_video_fields()
        self.assertEqual(fields['chapters'], [])
        self.assertFalse(fields['has_study_guide'])

    def test_the_study_guide_must_be_a_pdf(self):
        with self.assertRaises(ValidationError):
            self.youtube.write({'study_guide': base64.b64encode(b'hi'), 'study_guide_filename': 'guide.docx'})

    def test_an_enrolled_student_downloads_the_study_guide(self):
        token = self._token(self.student)
        Content = self.env['college.course.content']
        self.assertFalse(Content.app_college_my_study_guide(token, self.youtube.id)['success'])  # none yet
        self.youtube.write({'study_guide': base64.b64encode(PDF), 'study_guide_filename': 'exodus.pdf'})
        result = Content.app_college_my_study_guide(token, self.youtube.id)
        self.assertTrue(result['success'])
        self.assertEqual(result['filename'], 'exodus.pdf')
        self.assertEqual(base64.b64decode(result['data']), PDF)
        self.assertEqual(Content.app_college_my_study_guide('bad-token', self.youtube.id)['error'], 'Please sign in again')

    def test_another_course_study_guide_is_refused(self):
        token = self._token(self.student)
        other_course = self.env['college.course'].create({'name': 'Homiletics', 'program_id': self.program.id})
        other_module = self.env['college.course.module'].create({'name': 'M', 'course_id': other_course.id})
        other = self.env['college.course.content'].create({
            'name': 'Other', 'module_id': other_module.id, 'content_type': 'video',
            'study_guide': base64.b64encode(PDF), 'study_guide_filename': 'other.pdf',
        })
        self.assertEqual(self.env['college.course.content'].app_college_my_study_guide(token, other.id)['error'], 'Not found')

    def test_notes_and_bookmarks_are_saved_listed_in_time_order_and_edited(self):
        token = self._token(self.student)
        note = self.Note.app_college_my_note_save(token, self.lesson.id, 754.2, '  Passover = the Lamb  ')
        self.assertTrue(note['success'])
        self.assertEqual(note['note']['body'], 'Passover = the Lamb')
        bookmark = self.Note.app_college_my_note_save(token, self.lesson.id, 30)
        self.assertEqual(bookmark['note']['body'], '')  # no text = a bookmark

        listed = self.Note.app_college_my_notes(token, self.lesson.id)['notes']
        self.assertEqual([n['position'] for n in listed], [30.0, 754.2])

        edited = self.Note.app_college_my_note_save(
            token, self.lesson.id, 754.2, 'Passover points to Jesus', note_id=note['note']['id'])
        self.assertTrue(edited['success'])
        self.assertEqual(self.Note.browse(note['note']['id']).sudo().body, 'Passover points to Jesus')
        self.assertEqual(self.Note.sudo().search_count([('student_id', '=', self.student.id)]), 2)

        self.assertTrue(self.Note.app_college_my_note_delete(token, bookmark['note']['id'])['success'])
        self.assertEqual(len(self.Note.app_college_my_notes(token, self.lesson.id)['notes']), 1)

    def test_a_student_cannot_touch_another_students_notes(self):
        token = self._token(self.student)
        other = self.env['college.student'].create({'name': 'Ruth', 'email': 'ruth@example.com', 'program_id': self.program.id})
        self.env['college.enrollment'].create({'student_id': other.id, 'course_id': self.course.id, 'term_id': self.term.id})
        other_token = self._token(other)
        mine = self.Note.app_college_my_note_save(token, self.lesson.id, 10, 'Mine')['note']

        self.assertEqual(self.Note.app_college_my_notes(other_token, self.lesson.id)['notes'], [])
        self.assertEqual(self.Note.app_college_my_note_save(
            other_token, self.lesson.id, 10, 'Changed', note_id=mine['id'])['error'], 'Not found')
        self.assertEqual(self.Note.app_college_my_note_delete(other_token, mine['id'])['error'], 'Not found')
        self.assertEqual(self.Note.sudo().browse(mine['id']).body, 'Mine')

    def test_notes_need_an_enrolled_lesson_and_a_sensible_length(self):
        token = self._token(self.student)
        other_course = self.env['college.course'].create({'name': 'Homiletics', 'program_id': self.program.id})
        other_module = self.env['college.course.module'].create({'name': 'M', 'course_id': other_course.id})
        other = self.env['college.course.content'].create({'name': 'Other', 'module_id': other_module.id, 'content_type': 'video'})
        self.assertEqual(self.Note.app_college_my_note_save(token, other.id, 1, 'x')['error'], 'Not found')
        self.assertEqual(self.Note.app_college_my_notes(token, other.id)['error'], 'Not found')
        self.assertFalse(self.Note.app_college_my_note_save(token, self.lesson.id, 1, 'x' * 2001)['success'])
        self.assertEqual(self.Note.app_college_my_note_save('bad', self.lesson.id, 1, 'x')['error'], 'Please sign in again')
        self.assertEqual(self.Note.app_college_my_note_save(token, self.lesson.id, -5, 'x')['note']['position'], 0.0)

    def test_college_staff_and_admins_cannot_read_student_notes(self):
        token = self._token(self.student)
        self.Note.app_college_my_note_save(token, self.lesson.id, 10, 'Private thought')
        for group in ('revive_bible_college.group_college_staff', 'revive_bible_college.group_college_admin'):
            user = new_test_user(self.env, login='notes-%s' % group.split('_')[-1], groups='base.group_user,%s' % group)
            with self.assertRaises(AccessError):
                self.Note.with_user(user).search([])

    def test_notes_go_when_the_lesson_goes(self):
        token = self._token(self.student)
        self.Note.app_college_my_note_save(token, self.lesson.id, 10, 'Gone soon')
        self.lesson.unlink()
        self.assertEqual(self.Note.sudo().search_count([('student_id', '=', self.student.id)]), 0)


@tagged('post_install', '-at_install')
class TestCollegeTranscriptHttp(_VideoSetup, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()

    def test_a_youtube_lesson_streams_its_transcript_but_never_a_video(self):
        token = self._token(self.student)
        headers = {'X-College-Token': token}
        captions = '/college/video/%d/captions' % self.youtube.id
        self.assertEqual(self.url_open(captions, headers=headers).status_code, 404)
        self.youtube.write({'caption_file': base64.b64encode(VTT), 'caption_filename': 'intro.vtt'})
        response = self.url_open(captions, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'In the beginning', response.content)
        self.assertEqual(self.url_open(captions).status_code, 404)  # no token
        self.assertEqual(self.url_open('/college/video/%d' % self.youtube.id, headers=headers).status_code, 404)

    def test_a_non_video_lesson_never_serves_captions(self):
        token = self._token(self.student)
        text = self.env['college.course.content'].create({
            'name': 'Reading', 'module_id': self.module.id, 'content_type': 'text',
            'caption_file': base64.b64encode(VTT), 'caption_filename': 'x.vtt',
        })
        url = '/college/video/%d/captions' % text.id
        self.assertEqual(self.url_open(url, headers={'X-College-Token': token}).status_code, 404)
