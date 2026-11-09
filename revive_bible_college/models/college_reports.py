"""Reports for college staff and admins (Bible College > Reports).

Each report is a read-only database view, so it can be filtered, grouped
and sorted like any list, and exported with "Download Excel". Students'
private video notes are never part of any report."""
import base64
import io
import json
import math
from collections import Counter

from markupsafe import Markup, escape

from odoo import _, api, fields, models, tools

from .college_lesson_progress import WATCH_PIECE_SECONDS, decode_pieces

FALLING_BEHIND_DAYS = 14


def _clock(seconds):
    seconds = int(seconds or 0)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return '%d:%02d:%02d' % (hours, minutes, secs) if hours else '%d:%02d' % (minutes, secs)


class CollegeReportMixin(models.AbstractModel):
    """"Download Excel" for a report: the rows ticked in the list, or all
    of them when none are ticked, with the report's own columns."""
    _name = 'college.report.mixin'
    _description = 'Bible College report export'

    _excel_title = 'Report'

    def _excel_columns(self):
        """[(field name, column heading)] in the order to export."""
        raise NotImplementedError

    def _excel_value(self, record, name):
        field = record._fields[name]
        value = record[name]
        if field.type == 'many2one':
            return value.display_name or ''
        if field.type == 'boolean':
            return _('Yes') if value else _('No')
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, '') if value else ''
        if field.type in ('date', 'datetime'):
            return fields.Date.to_string(value) if field.type == 'date' and value else (
                fields.Datetime.to_string(value) if value else '')
        if field.type == 'float':
            return round(value or 0.0, 1)
        return value if value not in (False, None) else ''

    def _excel_bytes(self, records):
        import xlsxwriter  # shipped with Odoo
        columns = self._excel_columns()
        out = io.BytesIO()
        book = xlsxwriter.Workbook(out, {'in_memory': True})
        sheet = book.add_worksheet(self._excel_title[:31])
        head = book.add_format({'bold': True, 'bg_color': '#243467', 'font_color': '#FFFFFF', 'border': 1})
        for col, (_name, label) in enumerate(columns):
            sheet.write(0, col, label, head)
            sheet.set_column(col, col, max(12, len(label) + 2))
        for row, record in enumerate(records, start=1):
            for col, (name, _label) in enumerate(columns):
                sheet.write(row, col, self._excel_value(record, name))
        sheet.freeze_panes(1, 0)
        if records:
            sheet.autofilter(0, 0, len(records), len(columns) - 1)
        book.close()
        return out.getvalue()

    def action_download_excel(self):
        records = self or self.search([])
        filename = '%s %s.xlsx' % (self._excel_title, fields.Date.context_today(self))
        Attachment = self.env['ir.attachment'].sudo()
        # One file per person per report: replace their last download.
        Attachment.search([
            ('res_model', '=', self._name), ('res_id', '=', 0), ('create_uid', '=', self.env.uid),
            ('description', '=', 'college-report-export'),
        ]).unlink()
        attachment = Attachment.create({
            'name': filename, 'datas': base64.b64encode(self._excel_bytes(records)),
            'res_model': self._name, 'res_id': 0, 'description': 'college-report-export',
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {'type': 'ir.actions.act_url', 'url': '/web/content/%d?download=true' % attachment.id, 'target': 'self'}


class CollegeReportProgress(models.Model):
    """One row per student per course they are enrolled in."""
    _name = 'college.report.progress'
    _inherit = 'college.report.mixin'
    _description = 'Bible College report: student progress'
    _auto = False
    _order = 'last_active desc nulls last, id'
    _rec_name = 'student_id'
    _excel_title = 'Student progress'

    enrollment_id = fields.Many2one('college.enrollment', readonly=True)
    student_id = fields.Many2one('college.student', readonly=True)
    course_id = fields.Many2one('college.course', readonly=True)
    term_id = fields.Many2one('college.term', readonly=True)
    program_id = fields.Many2one('college.program', readonly=True)
    enrollment_state = fields.Selection(
        [('enrolled', 'Enrolled'), ('completed', 'Completed'), ('withdrawn', 'Withdrawn')], readonly=True)
    lessons_total = fields.Integer(string='Lessons', readonly=True)
    lessons_done = fields.Integer(string='Lessons done', readonly=True)
    percent_done = fields.Float(string='Done (%)', readonly=True, aggregator='avg')
    avg_watched = fields.Float(string='Videos watched (%)', readonly=True, aggregator='avg',
                               help='Average of how much of each video in the course the student has really watched.')
    avg_quiz = fields.Float(string='Average quiz score (%)', readonly=True, aggregator='avg',
                            help="Average of the student's best score on each quiz they have taken.")
    quizzes_taken = fields.Integer(readonly=True)
    has_certificate = fields.Boolean(string='Certificate', readonly=True)
    last_active = fields.Datetime(readonly=True)
    # Not finished, and no activity in the last FALLING_BEHIND_DAYS days
    # (or never started).
    falling_behind = fields.Boolean(compute='_compute_falling_behind', search='_search_falling_behind')

    def _cutoff(self):
        return fields.Datetime.subtract(fields.Datetime.now(), days=FALLING_BEHIND_DAYS)

    @api.depends('last_active', 'percent_done', 'enrollment_state')
    def _compute_falling_behind(self):
        cutoff = self._cutoff()
        for report in self:
            report.falling_behind = (
                report.enrollment_state == 'enrolled' and report.percent_done < 100
                and (not report.last_active or report.last_active < cutoff))

    def _search_falling_behind(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            return NotImplemented
        wanted = (operator == '=') == value
        domain = ['&', '&', ('enrollment_state', '=', 'enrolled'), ('percent_done', '<', 100),
                  '|', ('last_active', '=', False), ('last_active', '<', self._cutoff())]
        return domain if wanted else ['!'] + domain

    def _excel_columns(self):
        return [
            ('student_id', 'Student'), ('course_id', 'Course'), ('term_id', 'Term'), ('program_id', 'Program'),
            ('lessons_done', 'Lessons done'), ('lessons_total', 'Lessons'), ('percent_done', 'Done (%)'),
            ('avg_watched', 'Videos watched (%)'), ('avg_quiz', 'Average quiz score (%)'),
            ('quizzes_taken', 'Quizzes taken'), ('has_certificate', 'Certificate'), ('last_active', 'Last active'),
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT e.id AS id, e.id AS enrollment_id, e.student_id, e.course_id, e.term_id,
                       s.program_id, e.state AS enrollment_state,
                       COALESCE(lc.total, 0) AS lessons_total,
                       COALESCE(pd.done, 0) AS lessons_done,
                       CASE WHEN COALESCE(lc.total, 0) > 0
                            THEN ROUND(100.0 * COALESCE(pd.done, 0) / lc.total, 1) ELSE 0 END AS percent_done,
                       CASE WHEN COALESCE(lc.videos, 0) > 0
                            THEN ROUND((COALESCE(pd.watched_sum, 0) / lc.videos)::numeric, 1) ELSE 0 END AS avg_watched,
                       COALESCE(ROUND(qz.avg_best::numeric, 1), 0) AS avg_quiz,
                       COALESCE(qz.taken, 0) AS quizzes_taken,
                       EXISTS (SELECT 1 FROM college_certificate ce WHERE ce.enrollment_id = e.id) AS has_certificate,
                       pd.last_active
                  FROM college_enrollment e
                  JOIN college_student s ON s.id = e.student_id
             LEFT JOIN (SELECT course_id, COUNT(*) AS total,
                               COUNT(*) FILTER (WHERE content_type = 'video') AS videos
                          FROM college_course_content WHERE active GROUP BY course_id) lc ON lc.course_id = e.course_id
             LEFT JOIN LATERAL (
                        SELECT COUNT(*) FILTER (WHERE p.completed) AS done,
                               MAX(p.write_date) AS last_active,
                               SUM(COALESCE(p.watched_percent, 0)) FILTER (WHERE c.content_type = 'video') AS watched_sum
                          FROM college_lesson_progress p
                          JOIN college_course_content c ON c.id = p.content_id
                         WHERE p.student_id = e.student_id AND c.course_id = e.course_id AND c.active) pd ON TRUE
             LEFT JOIN LATERAL (
                        SELECT AVG(best.score) AS avg_best, COUNT(*) AS taken
                          FROM (SELECT MAX(a.score) AS score
                                  FROM college_quiz_attempt a
                                 WHERE a.student_id = e.student_id
                                   AND a.quiz_id IN (SELECT c.quiz_id FROM college_course_content c
                                                      WHERE c.course_id = e.course_id AND c.active
                                                        AND c.content_type = 'quiz' AND c.quiz_id IS NOT NULL)
                                 GROUP BY a.quiz_id) best) qz ON TRUE
            )""" % self._table)


class CollegeReportVideo(models.Model):
    """One row per video lesson."""
    _name = 'college.report.video'
    _inherit = 'college.report.mixin'
    _description = 'Bible College report: videos'
    _auto = False
    _order = 'course_id, content_id'
    _rec_name = 'content_id'
    _excel_title = 'Videos'

    content_id = fields.Many2one('college.course.content', string='Video lesson', readonly=True)
    course_id = fields.Many2one('college.course', readonly=True)
    module_id = fields.Many2one('college.course.module', readonly=True)
    video_source = fields.Selection(
        [('youtube', 'YouTube link'), ('upload', 'Upload from computer'), ('drive', 'Google Drive link')], readonly=True)
    students_enrolled = fields.Integer(readonly=True)
    students_started = fields.Integer(readonly=True)
    students_finished = fields.Integer(readonly=True)
    finished_percent = fields.Float(string='Finished (%)', readonly=True, aggregator='avg',
                                    help='Of the students enrolled in the course.')
    avg_watched = fields.Float(string='Average watched (%)', readonly=True, aggregator='avg',
                               help='Of the students who started it.')
    dropoff_html = fields.Html(string='Where students stop watching', compute='_compute_dropoff_html', sanitize=False)

    def _excel_columns(self):
        return [
            ('content_id', 'Video lesson'), ('course_id', 'Course'), ('module_id', 'Module'), ('video_source', 'Source'),
            ('students_enrolled', 'Students enrolled'), ('students_started', 'Started'),
            ('students_finished', 'Finished'), ('finished_percent', 'Finished (%)'),
            ('avg_watched', 'Average watched (%)'),
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT c.id AS id, c.id AS content_id, c.course_id, c.module_id, COALESCE(c.video_source, 'youtube') AS video_source,
                       COALESCE(en.students, 0) AS students_enrolled,
                       COALESCE(pr.started, 0) AS students_started,
                       COALESCE(pr.finished, 0) AS students_finished,
                       CASE WHEN COALESCE(en.students, 0) > 0
                            THEN ROUND(100.0 * COALESCE(pr.finished, 0) / en.students, 1) ELSE 0 END AS finished_percent,
                       COALESCE(ROUND(pr.avg_watched::numeric, 1), 0) AS avg_watched
                  FROM college_course_content c
             LEFT JOIN (SELECT course_id, COUNT(DISTINCT student_id) AS students
                          FROM college_enrollment GROUP BY course_id) en ON en.course_id = c.course_id
             LEFT JOIN (SELECT content_id, COUNT(*) AS started,
                               COUNT(*) FILTER (WHERE completed) AS finished,
                               AVG(COALESCE(watched_percent, 0)) AS avg_watched
                          FROM college_lesson_progress GROUP BY content_id) pr ON pr.content_id = c.id
                 WHERE c.content_type = 'video' AND c.active
            )""" % self._table)

    def _dropoff(self):
        """[(from seconds, to seconds, students who watched most of that tenth)]
        and how many students have watch data, for this video."""
        self.ensure_one()
        rows = self.env['college.lesson.progress'].sudo().search([
            ('content_id', '=', self.content_id.id), ('video_duration', '>', 0),
        ])
        length = max(rows.mapped('video_duration') or [0])
        if not rows or not length:
            return [], 0, 0
        total = max(1, math.ceil(length / WATCH_PIECE_SECONDS))
        tenths = [0] * 10
        for row in rows:
            pieces = decode_pieces(row.watched_ranges)
            for tenth in range(10):
                first, last = total * tenth // 10, max(total * (tenth + 1) // 10, total * tenth // 10 + 1)
                span = range(first, min(last, total))
                if span and sum(1 for p in span if p in pieces) * 2 >= len(span):
                    tenths[tenth] += 1
        return [(length * t / 10, length * (t + 1) / 10, tenths[t]) for t in range(10)], len(rows), length

    def _compute_dropoff_html(self):
        for report in self:
            bars, viewers, length = report._dropoff()
            if not viewers:
                report.dropoff_html = Markup('<p class="text-muted">%s</p>') % _(
                    'No watching recorded yet. This fills in as students watch the video in the app.')
                continue
            peak = max(count for _f, _t, count in bars) or 1
            lines = [Markup('<p class="text-muted mb-2">%s</p>') % _(
                'How many of the %(viewers)d students who opened the video watched each tenth of it '
                '(%(length)s long). A sudden drop shows where students stop.',
                viewers=viewers, length=_clock(length))]
            for start, end, count in bars:
                lines.append(Markup(
                    '<div class="d-flex align-items-center mb-1" style="gap:8px">'
                    '<span class="text-muted" style="width:110px;font-variant-numeric:tabular-nums">%s – %s</span>'
                    '<div style="flex:1;background:#F3ECDD;border-radius:4px;height:18px">'
                    '<div style="width:%s%%;background:#C8982E;height:18px;border-radius:4px"></div></div>'
                    '<span style="width:90px">%s</span></div>'
                ) % (escape(_clock(start)), escape(_clock(end)), round(100 * count / peak),
                     escape(_('%(count)d of %(viewers)d', count=count, viewers=viewers))))
            report.dropoff_html = Markup('').join(lines)


class _AnswerReportBase(models.AbstractModel):
    _name = 'college.report.answer.base'
    _inherit = 'college.report.mixin'
    _description = 'Bible College report: question answers'

    answers = fields.Integer(readonly=True)
    fully_right = fields.Integer(string='Fully right', readonly=True)
    percent_right = fields.Float(string='Right (%)', readonly=True, aggregator='avg')
    common_wrong = fields.Char(string='Most common wrong answer', compute='_compute_common_wrong')

    def _wrong_picks(self):
        """{report id: Counter of wrong answer texts}."""
        raise NotImplementedError

    def _compute_common_wrong(self):
        picks = self._wrong_picks()
        for report in self:
            counter = picks.get(report.id)
            if counter:
                text, count = counter.most_common(1)[0]
                report.common_wrong = _('%(answer)s (%(count)d×)', answer=text, count=count)
            else:
                report.common_wrong = ''


class CollegeReportQuizQuestion(models.Model):
    """One row per quiz question that has been answered, hardest first."""
    _name = 'college.report.quiz.question'
    _inherit = 'college.report.answer.base'
    _description = 'Bible College report: quiz questions'
    _auto = False
    _order = 'percent_right, answers desc, id'
    _rec_name = 'question_id'
    _excel_title = 'Quiz questions'

    question_id = fields.Many2one('college.quiz.question', string='Question', readonly=True)
    quiz_id = fields.Many2one('college.quiz', readonly=True)
    question_type = fields.Selection(
        lambda self: self.env['college.quiz.question']._fields['question_type'].selection, string='Type', readonly=True)
    avg_marks = fields.Float(string='Average marks (%)', readonly=True, aggregator='avg',
                             help='Includes part marks for choose-all, matching and put-in-order questions.')

    def _excel_columns(self):
        return [
            ('question_id', 'Question'), ('quiz_id', 'Quiz'), ('question_type', 'Type'), ('answers', 'Answers'),
            ('fully_right', 'Fully right'), ('percent_right', 'Right (%)'), ('avg_marks', 'Average marks (%)'),
            ('common_wrong', 'Most common wrong answer'),
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT q.id AS id, q.id AS question_id, q.quiz_id, q.question_type,
                       COUNT(a.id) AS answers,
                       COUNT(a.id) FILTER (WHERE a.is_correct) AS fully_right,
                       ROUND(100.0 * COUNT(a.id) FILTER (WHERE a.is_correct) / COUNT(a.id), 1) AS percent_right,
                       ROUND(100.0 * AVG(CASE WHEN a.credit IS NOT NULL THEN a.credit
                                              WHEN a.is_correct THEN 1 ELSE 0 END)::numeric, 1) AS avg_marks
                  FROM college_quiz_question q
                  JOIN college_quiz_answer a ON a.question_id = q.id
              GROUP BY q.id, q.quiz_id, q.question_type
            )""" % self._table)

    def _wrong_picks(self):
        result = {}
        answers = self.env['college.quiz.answer'].sudo().search([
            ('question_id', 'in', self.question_id.ids), ('is_correct', '=', False),
        ])
        for answer in answers:
            question = answer.question_id
            counter = result.setdefault(question.id, Counter())
            if question.question_type in ('single', False) and answer.option_id:
                counter[answer.option_id.text] += 1
            elif question.question_type == 'multiple' and answer.answer_text:
                try:
                    picked = set(json.loads(answer.answer_text))
                except (ValueError, TypeError):
                    continue
                wrong = question.option_ids.filtered(lambda o: o.id in picked and not o.is_correct)
                for option in wrong:
                    counter[option.text] += 1
            elif question.question_type in ('fill_blank', 'true_false') and answer.answer_text:
                try:
                    given = json.loads(answer.answer_text)
                except (ValueError, TypeError):
                    continue
                label = {True: _('True'), False: _('False')}.get(given, given) if isinstance(given, bool) else given
                if label not in (None, ''):
                    counter[str(label)] += 1
        return {report.id: result.get(report.question_id.id) for report in self}


class CollegeReportVideoQuestion(models.Model):
    """One row per in-video practice question that has been answered."""
    _name = 'college.report.video.question'
    _inherit = 'college.report.answer.base'
    _description = 'Bible College report: questions during videos'
    _auto = False
    _order = 'percent_right, answers desc, id'
    _rec_name = 'question_id'
    _excel_title = 'Questions during videos'

    question_id = fields.Many2one('college.video.question', string='Question', readonly=True)
    content_id = fields.Many2one('college.course.content', string='Video lesson', readonly=True)
    course_id = fields.Many2one('college.course', readonly=True)
    pause_time = fields.Char(string='At', readonly=True)

    def _excel_columns(self):
        return [
            ('question_id', 'Question'), ('content_id', 'Video lesson'), ('course_id', 'Course'),
            ('pause_time', 'At'), ('answers', 'Answers'), ('fully_right', 'Right'),
            ('percent_right', 'Right (%)'), ('common_wrong', 'Most common wrong answer'),
        ]

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT q.id AS id, q.id AS question_id, q.content_id, c.course_id, q.pause_time,
                       COUNT(a.id) AS answers,
                       COUNT(a.id) FILTER (WHERE a.is_correct) AS fully_right,
                       ROUND(100.0 * COUNT(a.id) FILTER (WHERE a.is_correct) / COUNT(a.id), 1) AS percent_right
                  FROM college_video_question q
                  JOIN college_course_content c ON c.id = q.content_id
                  JOIN college_video_question_answer a ON a.question_id = q.id
              GROUP BY q.id, q.content_id, c.course_id, q.pause_time
            )""" % self._table)

    def _wrong_picks(self):
        result = {}
        for answer in self.env['college.video.question.answer'].sudo().search([
            ('question_id', 'in', self.question_id.ids), ('is_correct', '=', False), ('option_id', '!=', False),
        ]):
            result.setdefault(answer.question_id.id, Counter())[answer.option_id.text] += 1
        return {report.id: result.get(report.question_id.id) for report in self}
