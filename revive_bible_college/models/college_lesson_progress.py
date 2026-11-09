import math

from odoo import api, fields, models

from .college_app_api import token_student

# Watching is tracked in 5-second pieces of the video: piece n is seconds
# [5n, 5n + 5). A piece counts once it has actually been played.
WATCH_PIECE_SECONDS = 5
# Long enough for a ten-hour video; anything past it is ignored.
MAX_WATCH_PIECES = 7200


def decode_pieces(text):
    """{piece numbers} from "0-35,40,42-80"; anything unreadable is skipped."""
    pieces = set()
    for part in (text or '').split(','):
        start, _sep, end = part.strip().partition('-')
        try:
            low = int(start)
            high = int(end) if end else low
        except ValueError:
            continue
        low, high = max(0, low), min(high, MAX_WATCH_PIECES - 1)
        if low <= high:
            pieces.update(range(low, high + 1))
    return pieces


def encode_pieces(pieces):
    """The compact "0-35,40,42-80" form of a set of piece numbers."""
    parts, run_start, previous = [], None, None
    for piece in sorted(pieces):
        if run_start is None:
            run_start = previous = piece
        elif piece == previous + 1:
            previous = piece
        else:
            parts.append(str(run_start) if run_start == previous else '%d-%d' % (run_start, previous))
            run_start = previous = piece
    if run_start is not None:
        parts.append(str(run_start) if run_start == previous else '%d-%d' % (run_start, previous))
    return ','.join(parts)


def watched_percent(pieces, duration):
    """How much of a video of `duration` seconds those pieces cover."""
    if not duration or duration <= 0:
        return 0.0
    total = max(1, math.ceil(duration / WATCH_PIECE_SECONDS))
    return min(100.0, 100.0 * len([p for p in pieces if p < total]) / total)


class CollegeLessonProgress(models.Model):
    """One student's progress on one lesson: whether they have started or
    finished it, and, for a video, where to resume and which parts they have
    really watched. Rows are created lazily, the first time a student opens
    or completes a lesson."""
    _name = 'college.lesson.progress'
    _description = "A student's lesson progress"
    _order = 'id desc'
    _rec_name = 'content_id'

    student_id = fields.Many2one('college.student', required=True, ondelete='cascade', index=True)
    content_id = fields.Many2one('college.course.content', required=True, ondelete='cascade', index=True)
    started = fields.Boolean(default=True)
    completed = fields.Boolean(default=False)
    completed_date = fields.Datetime(readonly=True)
    video_position = fields.Float(string='Video Position (seconds)', default=0.0)
    watched_ranges = fields.Text(string='Watched parts', readonly=True,
                                 help='5-second pieces of the video actually played, like "0-35,40-80".')
    video_duration = fields.Float(string='Video length (seconds)', readonly=True)
    watched_percent = fields.Float(string='Watched (%)', readonly=True, digits=(5, 1))

    _student_content_uniq = models.Constraint(
        'unique(student_id, content_id)', 'Already have a progress record for this lesson.')

    def _video_status(self):
        """Where this video stands against its completion rule."""
        self.ensure_one()
        content = self.content_id
        min_percent, _require = content._completion_rule()
        answered = set(self.env['college.video.question.answer'].sudo().search([
            ('student_id', '=', self.student_id.id), ('question_id.content_id', '=', content.id),
        ]).question_id.ids)
        questions_left = content._questions_left(answered)
        percent = self.watched_percent or 0.0
        short = percent + 1e-9 < min_percent
        if short:
            message = 'Watch at least %d%% of this video to finish it (you have watched %d%%).' % (min_percent, int(percent))
        elif questions_left:
            message = 'Answer the %s in this video to finish it.' % (
                'question' if questions_left == 1 else '%d questions' % questions_left)
        else:
            message = ''
        return {
            'rule_met': not short and not questions_left,
            'watched_percent': round(percent, 1),
            'min_watch_percent': min_percent,
            'questions_left': questions_left,
            'message': message,
        }

    def _complete(self):
        self.ensure_one()
        if not self.completed:
            self.write({'completed': True, 'completed_date': fields.Datetime.now()})
            self.env['college.badge.award'].sudo()._check_lesson_complete(self.student_id, self.content_id)

    @api.model
    def _for(self, student, content):
        progress = self.sudo().search([('student_id', '=', student.id), ('content_id', '=', content.id)], limit=1)
        return progress or self.sudo().create({'student_id': student.id, 'content_id': content.id})

    @api.model
    def _sync_video_completion(self, student, content):
        """Finishes a video lesson the moment its rule is met (once complete,
        it stays complete). Returns the progress row."""
        progress = self._for(student, content)
        if not progress.completed and progress._video_status()['rule_met']:
            progress._complete()
        return progress

    @api.model
    def app_college_my_progress_save(self, token, content_id, video_position=None, completed=None,
                                     watched=None, duration=None):
        """Saves where a student is in a lesson. For a video, `watched` adds
        the pieces just played ("0-35,40"), `duration` is its length in
        seconds, and the server decides when it is complete: a request to
        mark it done before its rule is met is refused with the reason."""
        student = token_student(self.env, token)
        if not student:
            return {'success': False, 'error': 'Please sign in again'}
        content = self.env['college.course.content'].sudo().browse(content_id)
        enrolled_course_ids = set(student.enrollment_ids.course_id.ids)
        if not content.exists() or content.course_id.id not in enrolled_course_ids:
            return {'success': False, 'error': 'Not found'}
        progress = self._for(student, content)
        vals = {'started': True}
        if video_position is not None:
            vals['video_position'] = max(0.0, float(video_position))
        is_video = content.content_type == 'video'
        if is_video and (watched or duration):
            length = max(progress.video_duration or 0.0, float(duration or 0.0))
            pieces = decode_pieces(progress.watched_ranges) | decode_pieces(watched)
            vals.update({
                'video_duration': length,
                'watched_ranges': encode_pieces(pieces) or False,
                'watched_percent': watched_percent(pieces, length),
            })
        progress.write(vals)

        if completed is False:
            progress.write({'completed': False, 'completed_date': False})
        elif is_video:
            status = progress._video_status()
            if completed and not progress.completed and not status['rule_met']:
                return {'success': False, 'error': status['message'], **status, 'completed': False}
            if status['rule_met']:
                progress._complete()
            return {'success': True, 'completed': progress.completed, **status}
        elif completed:
            progress._complete()
        return {'success': True, 'completed': progress.completed}
