from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.revive_bible_college.models.college_lesson_progress import (
    decode_pieces, encode_pieces, watched_percent,
)

from .test_college_video import _VideoSetup


class TestWatchPieces(TransactionCase):

    def test_pieces_round_trip_in_a_compact_form(self):
        self.assertEqual(encode_pieces({0, 1, 2, 3, 7, 9, 10}), '0-3,7,9-10')
        self.assertEqual(decode_pieces('0-3,7,9-10'), {0, 1, 2, 3, 7, 9, 10})
        self.assertEqual(encode_pieces(set()), '')
        self.assertEqual(decode_pieces(''), set())
        self.assertEqual(decode_pieces(False), set())

    def test_junk_and_out_of_range_pieces_are_ignored(self):
        self.assertEqual(decode_pieces('2,x,5-a,-4,3-1, 6 '), {2, 6})
        self.assertEqual(len(decode_pieces('0-999999')), 7200)

    def test_percent_counts_each_piece_once_against_the_length(self):
        # A 100-second video is 20 pieces.
        self.assertEqual(watched_percent(set(range(10)), 100), 50.0)
        self.assertEqual(watched_percent(set(range(20)), 100), 100.0)
        self.assertEqual(watched_percent(set(range(40)), 100), 100.0)  # pieces past the end don't count
        self.assertEqual(watched_percent({0}, 2), 100.0)
        self.assertEqual(watched_percent(set(range(10)), 0), 0.0)


class TestWatchCompletion(_VideoSetup, TransactionCase):
    """A 100-second video (20 pieces), using the course's rule unless a test
    sets the lesson's own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_course()
        cls.Progress = cls.env['college.lesson.progress']
        cls.Question = cls.env['college.video.question']

    def setUp(self):
        super().setUp()
        self.token = self._token(self.student)

    def save(self, lesson=None, **kwargs):
        return self.Progress.app_college_my_progress_save(self.token, (lesson or self.youtube).id, **kwargs)

    def _row(self, lesson=None):
        return self.Progress.search([('student_id', '=', self.student.id), ('content_id', '=', (lesson or self.youtube).id)])

    def test_courses_default_to_90_percent_and_answering_questions(self):
        self.assertEqual(self.course.video_min_watch_percent, 90)
        self.assertTrue(self.course.video_require_questions)
        self.assertEqual(self.youtube._completion_rule(), (90, True))

    def test_watching_adds_up_and_finishes_the_video_at_the_rule(self):
        result = self.save(video_position=50, watched='0-9', duration=100)
        self.assertEqual(result['watched_percent'], 50.0)
        self.assertFalse(result['completed'])
        self.assertEqual(result['min_watch_percent'], 90)
        # Rewatching the same part adds nothing.
        self.assertEqual(self.save(watched='0-9', duration=100)['watched_percent'], 50.0)
        self.assertEqual(self.save(watched='10-16', duration=100)['watched_percent'], 85.0)
        result = self.save(watched='17', duration=100)
        self.assertEqual(result['watched_percent'], 90.0)
        self.assertTrue(result['completed'])
        self.assertEqual(self._row().watched_ranges, '0-17')
        self.assertTrue(self.env['college.badge.award'].search([('student_id', '=', self.student.id), ('kind', '=', 'first_lesson')]))

    def test_skipping_to_the_end_does_not_finish_it(self):
        result = self.save(video_position=99, watched='0-1,19', duration=100)
        self.assertEqual(result['watched_percent'], 15.0)
        self.assertFalse(result['completed'])

    def test_marking_done_too_early_is_refused_with_the_reason(self):
        self.save(watched='0-12', duration=100)
        result = self.save(completed=True)
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], 'Watch at least 90% of this video to finish it (you have watched 65%).')
        self.assertFalse(self._row().completed)

    def test_every_question_must_be_answered_when_the_rule_says_so(self):
        question = self.Question.create({
            'content_id': self.youtube.id, 'pause_time': '0:30', 'text': 'Who led Israel?',
            'option_ids': [(0, 0, {'text': 'Moses', 'is_correct': True}), (0, 0, {'text': 'Joshua'})],
        })
        result = self.save(watched='0-19', duration=100)
        self.assertEqual(result['watched_percent'], 100.0)
        self.assertEqual(result['questions_left'], 1)
        self.assertFalse(result['completed'])
        self.assertEqual(self.save(completed=True)['error'], 'Answer the question in this video to finish it.')
        # A wrong answer still counts, and is what finishes the lesson.
        answer = self.Question.app_college_my_video_answer(self.token, question.id, question.option_ids[1].id)
        self.assertFalse(answer['is_correct'])
        self.assertTrue(answer['lesson_completed'])
        self.assertTrue(self._row().completed)

    def test_a_lesson_can_set_its_own_rule(self):
        self.Question.create({
            'content_id': self.youtube.id, 'pause_time': '0:30', 'text': 'Q?',
            'option_ids': [(0, 0, {'text': 'A', 'is_correct': True})],
        })
        self.youtube.write({'completion_override': True, 'min_watch_percent': 50, 'require_questions': False})
        self.assertEqual(self.youtube._completion_rule(), (50, False))
        result = self.save(watched='0-9', duration=100)
        self.assertEqual(result['questions_left'], 0)
        self.assertTrue(result['completed'])

    def test_the_course_rule_covers_its_videos(self):
        self.course.write({'video_min_watch_percent': 25, 'video_require_questions': False})
        self.assertTrue(self.save(watched='0-4', duration=100)['completed'])

    def test_a_finished_video_stays_finished(self):
        self.save(watched='0-19', duration=100)
        self.youtube.write({'completion_override': True, 'min_watch_percent': 100})
        self.Question.create({'content_id': self.youtube.id, 'pause_time': '0:30', 'text': 'New question?',
                              'option_ids': [(0, 0, {'text': 'A', 'is_correct': True})]})
        result = self.save(video_position=10)
        self.assertTrue(result['success'])
        self.assertTrue(result['completed'])
        self.assertTrue(self.save(completed=True)['success'])

    def test_already_completed_rows_from_before_this_update_are_kept(self):
        # A row completed by the old "near the end" rule, with no watch data.
        self.Progress.create({'student_id': self.student.id, 'content_id': self.youtube.id, 'completed': True})
        result = self.save(video_position=5)
        self.assertTrue(result['completed'])

    def test_the_student_can_still_unmark_a_video(self):
        self.save(watched='0-19', duration=100)
        self.assertTrue(self.save(completed=False)['success'])
        self.assertFalse(self._row().completed)

    def test_the_longest_reported_length_wins(self):
        self.save(watched='0-9', duration=100)
        # A player that hasn't loaded the length yet reports 0.
        self.assertEqual(self.save(watched='10', duration=0)['watched_percent'], 55.0)
        self.assertEqual(self._row().video_duration, 100.0)

    def test_other_lesson_types_still_mark_done_by_hand(self):
        reading = self.env['college.course.content'].create({'name': 'Reading', 'module_id': self.module.id, 'content_type': 'text'})
        result = self.save(lesson=reading, completed=True, watched='0-3', duration=100)
        self.assertEqual(result, {'success': True, 'completed': True})
        self.assertFalse(self._row(reading).watched_ranges)

    def test_the_lesson_list_tells_the_app_where_the_student_stands(self):
        self.Question.create({
            'content_id': self.youtube.id, 'pause_time': '0:30', 'text': 'Q?',
            'option_ids': [(0, 0, {'text': 'A', 'is_correct': True})],
        })
        self.save(watched='0-5,8', duration=100)
        lessons = {l['id']: l for l in self.student._app_self_detail()['enrollments'][0]['modules'][0]['lessons']}
        lesson = lessons[self.youtube.id]
        self.assertEqual(lesson['watched_percent'], 35.0)
        self.assertEqual(lesson['watched_ranges'], '0-5,8')
        self.assertEqual(lesson['min_watch_percent'], 90)
        self.assertTrue(lesson['require_questions'])
        self.assertEqual(lesson['questions_left'], 1)
        self.assertEqual(lessons[self.lesson.id]['watched_percent'], 0.0)  # never opened

    def test_rule_percent_must_be_sensible(self):
        with self.assertRaises(ValidationError):
            self.course.video_min_watch_percent = 120
        with self.assertRaises(ValidationError):
            self.youtube.min_watch_percent = -1
