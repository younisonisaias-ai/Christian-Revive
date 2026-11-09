"""Course lessons and study activity for the LMS tabs (Quizzes, Flashcards,
Certificates, Badges, Reports), on top of sample_data.py.

Run sample_data.py first, then this, with `odoo shell`:

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db --no-http \
        < /path/to/revive_bible_college/scripts/lms_sample_data.py

What it adds:
* modules, readings, a quiz (all six question types) and a flashcard deck
  for every course that has no modules yet;
* study activity for the sample students, made through the same calls the
  app uses, so progress, quiz attempts, watch tracking, badges and
  certificates come out exactly as they would for a real student.

Sarah Masih's Old Testament Survey is left untouched, since that account is
the one used for trying the app. Like sample_data.py it remembers what it
created, so remove_sample_data.py takes it out again (lessons someone else
added to its modules are kept). Running it twice adds nothing the second time.
"""
import json

PARAM = 'revive_bible_college.sample_data_lms'
BASE_PARAM = 'revive_bible_college.sample_data'
# Children first: the order they can be deleted in.
MODELS = [
    'college.video.question.answer', 'college.quiz.attempt', 'college.flashcard.progress',
    'college.lesson.progress', 'college.badge.award', 'college.certificate', 'college.student.session',
    'college.flashcard', 'college.flashcard.deck', 'college.quiz.question', 'college.quiz',
    'college.course.content', 'college.course.module',
]

admin = env.ref('base.user_admin')
env = env(user=admin.id, su=True)
Params = env['ir.config_parameter']


def opts(pairs):
    return [(0, 0, {'text': t, 'is_correct': ok, 'sequence': i}) for i, (t, ok) in enumerate(pairs)]


def pairs_(items):
    return [(0, 0, {'text': t, 'match_text': m, 'sequence': i}) for i, (t, m) in enumerate(items)]


def order_(items):
    return [(0, 0, {'text': t, 'sequence': i}) for i, t in enumerate(items)]


# ── What each course gets (only courses with no modules yet) ─────────
# Each course: [(module, [(reading title, text)])], quiz, deck.
COURSES = {
    'Old Testament Survey': {
        'modules': [
            ('The Pentateuch', [
                ('The Five Books of Moses',
                 "Genesis, Exodus, Leviticus, Numbers and Deuteronomy are called the Pentateuch, or the Torah. "
                 "They tell how God created the world, called Abraham, rescued Israel from Egypt and gave the law "
                 "at Mount Sinai.\n\nRead them as one story: promise (Genesis), rescue (Exodus), holiness "
                 "(Leviticus), wilderness testing (Numbers) and renewal of the covenant (Deuteronomy)."),
                ('Covenant in Genesis',
                 "God's covenant with Abraham in Genesis 12, 15 and 17 promises land, descendants and blessing "
                 "to all nations. The rest of the Bible traces how God keeps that promise.\n\nNotice that the "
                 "covenant rests on God's faithfulness: in Genesis 15 God alone passes between the pieces."),
            ]),
            ('The Prophets', [
                ('Major and Minor Prophets',
                 "The 'major' prophets (Isaiah, Jeremiah, Ezekiel, Daniel) are longer books, not more important "
                 "ones. The twelve 'minor' prophets, Hosea to Malachi, are shorter.\n\nThe prophets called Israel "
                 "back to the covenant, warned of judgement and promised a coming Messiah (Isaiah 53, Micah 5:2)."),
            ]),
        ],
        'quiz': ('The Pentateuch', [
            ('true_false', 'Deuteronomy is one of the five books of Moses.', {'tf_answer': 'true'}, 'The Pentateuch is Genesis to Deuteronomy.'),
            ('single', 'In which book does God give the Ten Commandments?', {'option_ids': opts([('Genesis', False), ('Exodus', True), ('Leviticus', False), ('Numbers', False)])}, 'Exodus 20.'),
            ('multiple', 'Which of these are major prophets? Choose all that apply.', {'option_ids': opts([('Isaiah', True), ('Jeremiah', True), ('Amos', False), ('Ezekiel', True)])}, 'Amos is one of the twelve minor prophets.'),
            ('fill_blank', 'Fill in the blank: "In the beginning God created the heaven and the ___." (Genesis 1:1)', {'accepted_answers': 'earth\nthe earth'}, 'Genesis 1:1.'),
            ('matching', 'Match each book to what it is known for.', {'option_ids': pairs_([('Genesis', 'Beginnings'), ('Exodus', 'Rescue from Egypt'), ('Leviticus', 'Holiness and sacrifice'), ('Numbers', 'Wilderness years')])}, 'Each book carries the story one step further.'),
            ('ordering', 'Put these in the order they happen in Genesis.', {'option_ids': order_(['Creation', 'The flood', 'The call of Abraham', 'Joseph in Egypt'])}, 'Genesis 1, 6-9, 12 and 37-50.'),
        ]),
        'deck': ('Books of the Pentateuch', [
            ('Genesis', 'Beginnings: creation, the fall, the flood and the patriarchs.'),
            ('Exodus', 'Israel rescued from Egypt; the law given at Sinai.'),
            ('Leviticus', 'Laws for worship, sacrifice and holy living.'),
            ('Numbers', 'Forty years in the wilderness.'),
            ('Deuteronomy', "Moses' farewell sermons renewing the covenant."),
        ]),
    },
    'New Testament Survey': {
        'modules': [
            ('The Gospels', [
                ('Four Gospels, One Jesus',
                 "Matthew, Mark and Luke are called the synoptic Gospels because they 'see together': they share "
                 "much of the same material. John writes differently, with long conversations and seven signs.\n\n"
                 "Matthew writes for a Jewish audience, Mark for action, Luke as a careful historian, and John "
                 "'that ye might believe that Jesus is the Christ' (John 20:31)."),
                ('The Kingdom of God',
                 "Jesus began his preaching with 'The kingdom of God is at hand: repent ye, and believe the "
                 "gospel' (Mark 1:15). The kingdom is God's rule, already present in Jesus and still to come in "
                 "full.\n\nThe parables of Matthew 13 show the kingdom growing from small beginnings."),
            ]),
            ('Acts and the Letters', [
                ("Paul's Missionary Journeys",
                 "Acts follows the gospel from Jerusalem to Rome (Acts 1:8). Paul made three missionary journeys, "
                 "planting churches across Asia Minor and Greece, then travelled to Rome as a prisoner.\n\nMany of "
                 "his letters were written to the churches he planted: Galatians, Thessalonians, Corinthians, "
                 "Philippians and Ephesians."),
            ]),
        ],
        'quiz': ('Gospels and Acts', [
            ('true_false', 'John is one of the synoptic Gospels.', {'tf_answer': 'false'}, 'The synoptic Gospels are Matthew, Mark and Luke.'),
            ('single', 'Who wrote the book of Acts?', {'option_ids': opts([('Peter', False), ('Luke', True), ('Paul', False), ('John', False)])}, 'Luke wrote both his Gospel and Acts (Acts 1:1).'),
            ('multiple', 'Which of these did Paul write? Choose all that apply.', {'option_ids': opts([('Romans', True), ('Galatians', True), ('Hebrews', False), ('Philippians', True)])}, 'The writer of Hebrews is not named in the letter.'),
            ('fill_blank', 'Fill in the blank: "For God so loved the ___." (John 3:16)', {'accepted_answers': 'world\nthe world'}, 'John 3:16.'),
            ('matching', 'Match each Gospel to its main audience.', {'option_ids': pairs_([('Matthew', 'Jewish readers'), ('Luke', 'Theophilus'), ('John', 'All who might believe')])}, 'Matthew 1:1, Luke 1:3, John 20:31.'),
            ('ordering', 'Put these in the order of the New Testament.', {'option_ids': order_(['Matthew', 'Acts', 'Romans', 'Revelation'])}, 'Gospels, history, letters, prophecy.'),
        ]),
        'deck': ('New Testament Key Verses', [
            ('John 3:16', 'For God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life.'),
            ('Romans 3:23', 'For all have sinned, and come short of the glory of God.'),
            ('Romans 6:23', 'For the wages of sin is death; but the gift of God is eternal life through Jesus Christ our Lord.'),
            ('Ephesians 2:8', 'For by grace are ye saved through faith; and that not of yourselves: it is the gift of God.'),
            ('Acts 1:8', 'Ye shall be witnesses unto me both in Jerusalem, and in all Judaea, and in Samaria, and unto the uttermost part of the earth.'),
        ]),
    },
    'Systematic Theology': {
        'modules': [
            ('Knowing God', [
                ('Revelation',
                 "God makes himself known in two ways. General revelation is what all people can see of God in "
                 "creation and conscience (Psalm 19:1, Romans 1:20). Special revelation is God's word, written in "
                 "Scripture and made flesh in Jesus Christ (Hebrews 1:1-2).\n\nGeneral revelation leaves us without "
                 "excuse; only special revelation tells us how to be saved."),
                ('The Trinity',
                 "There is one God (Deuteronomy 6:4) who exists eternally as three persons: Father, Son and Holy "
                 "Spirit (Matthew 28:19). Each is fully God, and they are not three gods.\n\nThe word 'Trinity' is "
                 "not in the Bible, but it summarises what the Bible teaches."),
            ]),
            ('Salvation', [
                ('Justification by Faith',
                 "To be justified is to be declared righteous by God. Paul teaches that this comes 'by faith "
                 "without the deeds of the law' (Romans 3:28), because Christ's righteousness is counted to the "
                 "believer.\n\nGood works do not earn justification; they follow from it (Ephesians 2:8-10)."),
            ]),
        ],
        'quiz': ('Core Doctrines', [
            ('true_false', 'The word "Trinity" appears in the Bible.', {'tf_answer': 'false'}, 'The word is not there, but the teaching is.'),
            ('single', 'What does "justified" mean?', {'option_ids': opts([('Made perfect in behaviour', False), ('Declared righteous by God', True), ('Baptised', False), ('Forgiven by the church', False)])}, 'Romans 3:28, 5:1.'),
            ('multiple', 'Which are persons of the Trinity? Choose all that apply.', {'option_ids': opts([('The Father', True), ('The Son', True), ('Mary', False), ('The Holy Spirit', True)])}, 'Matthew 28:19.'),
            ('fill_blank', 'Revelation seen in creation and conscience is called ___ revelation.', {'accepted_answers': 'general'}, 'General revelation (Psalm 19:1, Romans 1:20).'),
            ('matching', 'Match each term to its meaning.', {'option_ids': pairs_([('Justification', 'Declared righteous'), ('Sanctification', 'Made holy over time'), ('Glorification', 'Made perfect in glory')])}, 'Romans 8:30.'),
            ('ordering', 'Put these in the order of Romans 8:30.', {'option_ids': order_(['Predestined', 'Called', 'Justified', 'Glorified'])}, '"Whom he did predestinate, them he also called..."'),
        ]),
        'deck': ('Theology Terms', [
            ('Revelation', 'God making himself known, in creation and in Scripture.'),
            ('Trinity', 'One God in three persons: Father, Son and Holy Spirit.'),
            ('Incarnation', 'God the Son becoming fully human while remaining fully God.'),
            ('Justification', 'God declaring a sinner righteous through faith in Christ.'),
            ('Sanctification', 'The lifelong work of the Spirit making a believer holy.'),
            ('Atonement', "Christ's work on the cross reconciling sinners to God."),
        ]),
    },
    'Church History': {
        'modules': [
            ('The Early Church', [
                ('Persecution and Growth',
                 "For nearly three centuries Christians faced waves of persecution under Roman emperors. Yet the "
                 "church grew: Tertullian wrote that the blood of the martyrs is seed.\n\nIn 313 the Edict of "
                 "Milan gave Christians legal freedom to worship."),
                ('The Council of Nicaea',
                 "In 325 the first church-wide council met at Nicaea to answer Arius, who taught that the Son was "
                 "a created being. The council confessed that the Son is 'of one substance with the Father'.\n\n"
                 "The Nicene Creed is still said in many churches today."),
            ]),
            ('The Reformation', [
                ('The Protestant Reformation',
                 "On 31 October 1517 Martin Luther posted his Ninety-five Theses in Wittenberg. The Reformation "
                 "that followed is often summed up in the 'solas': Scripture alone, grace alone, faith alone, "
                 "Christ alone, to the glory of God alone.\n\nOther reformers included Zwingli, Calvin and Knox."),
            ]),
        ],
        'quiz': ('Church History Milestones', [
            ('true_false', 'The Edict of Milan gave Christians freedom to worship.', {'tf_answer': 'true'}, 'AD 313.'),
            ('single', 'In which year did Luther post the Ninety-five Theses?', {'option_ids': opts([('1417', False), ('1517', True), ('1617', False), ('1717', False)])}, '31 October 1517.'),
            ('multiple', 'Which of these were Protestant reformers? Choose all that apply.', {'option_ids': opts([('John Calvin', True), ('Ulrich Zwingli', True), ('Constantine', False), ('John Knox', True)])}, 'Constantine was the Roman emperor of the early 300s.'),
            ('fill_blank', 'The council that met in AD 325 is the Council of ___.', {'accepted_answers': 'Nicaea\nNicea\nNicaea, AD 325'}, 'The Council of Nicaea.'),
            ('matching', 'Match each person to what they are known for.', {'option_ids': pairs_([('Luther', 'Ninety-five Theses'), ('Arius', 'Taught the Son was created'), ('Constantine', 'Called the Council of Nicaea')])}, 'Nicaea answered Arius; Luther began the Reformation.'),
            ('ordering', 'Put these in order, earliest first.', {'option_ids': order_(['Edict of Milan (313)', 'Council of Nicaea (325)', 'Ninety-five Theses (1517)'])}, '313, 325, 1517.'),
        ]),
        'deck': ('Key Dates in Church History', [
            ('AD 30', 'Pentecost: the Holy Spirit comes on the church (Acts 2).'),
            ('AD 313', 'Edict of Milan: freedom of worship for Christians.'),
            ('AD 325', 'Council of Nicaea and the Nicene Creed.'),
            ('1517', "Luther's Ninety-five Theses begin the Reformation."),
            ('1611', 'The King James Version of the Bible is published.'),
        ]),
    },
    'Pastoral Care': {
        'modules': [
            ('Caring for People', [
                ('Listening Well',
                 "James 1:19 says 'let every man be swift to hear, slow to speak'. Good pastoral care begins with "
                 "listening: giving full attention, asking open questions and not rushing to give answers.\n\n"
                 "People in pain often need presence more than explanations. Job's friends did best in the first "
                 "seven days, when they sat with him in silence (Job 2:13)."),
                ('Visiting the Sick',
                 "Jesus said, 'I was sick, and ye visited me' (Matthew 25:36). Keep hospital visits short, wash "
                 "your hands, respect the patient's privacy and ask before praying.\n\nRead a short psalm, such "
                 "as Psalm 23 or 121, and leave the person with a word of hope."),
            ]),
        ],
        'quiz': ('Pastoral Care Basics', [
            ('true_false', 'A hospital visit should usually be short.', {'tf_answer': 'true'}, 'Sick people tire quickly.'),
            ('single', 'According to James 1:19, we should be...', {'option_ids': opts([('Swift to speak', False), ('Swift to hear', True), ('Swift to judge', False), ('Swift to leave', False)])}, '"Swift to hear, slow to speak, slow to wrath."'),
            ('multiple', 'Which are good habits on a hospital visit? Choose all that apply.', {'option_ids': opts([('Ask before praying', True), ('Stay for several hours', False), ('Respect privacy', True), ('Wash your hands', True)])}, 'Short, respectful and clean.'),
            ('fill_blank', '"I was sick, and ye ___ me." (Matthew 25:36)', {'accepted_answers': 'visited'}, 'Matthew 25:36.'),
            ('matching', 'Match each psalm to its theme.', {'option_ids': pairs_([('Psalm 23', 'The Lord is my shepherd'), ('Psalm 121', 'My help comes from the Lord'), ('Psalm 51', 'A prayer of repentance')])}, 'Psalms for different needs.'),
            ('ordering', 'Put the steps of a short visit in order.', {'option_ids': order_(['Greet and listen', 'Read a short psalm', 'Ask to pray, then pray', 'Leave a word of hope'])}, 'Listen first, then Scripture, then prayer.'),
        ]),
        'deck': ('Verses of Comfort', [
            ('Psalm 23:1', 'The LORD is my shepherd; I shall not want.'),
            ('Psalm 46:1', 'God is our refuge and strength, a very present help in trouble.'),
            ('Matthew 11:28', 'Come unto me, all ye that labour and are heavy laden, and I will give you rest.'),
            ('2 Corinthians 1:4', 'Who comforteth us in all our tribulation, that we may be able to comfort them which are in any trouble.'),
            ('Isaiah 41:10', 'Fear thou not; for I am with thee: be not dismayed; for I am thy God.'),
        ]),
    },
    'Homiletics': {
        'modules': [
            ('Foundations of Preaching', [
                ('What Is Homiletics?',
                 "Homiletics is the art and science of preparing and preaching sermons. It stands beside "
                 "hermeneutics: hermeneutics asks what a passage means; homiletics asks how to proclaim that "
                 "meaning faithfully to these listeners today."),
            ]),
            ('Preparing the Sermon', [
                ('The Big Idea and the Outline',
                 "Every sermon should be able to say its main point in one clear sentence: the big idea. Then "
                 "build an outline that serves it: an introduction, two to four main points from the text, and "
                 "a conclusion that calls for a response."),
            ]),
        ],
        'quiz': ('Building a Sermon', [
            ('true_false', 'Exegesis means reading your own ideas into the text.', {'tf_answer': 'false'}, 'That is eisegesis.'),
            ('single', 'What is homiletics?', {'option_ids': opts([('The art and science of preaching', True), ('The study of hymns', False), ('Church history', False)])}, 'Preparing and preaching sermons.'),
            ('multiple', "Which belong in a sermon's introduction? Choose all that apply.", {'option_ids': opts([('Gain attention', True), ('Introduce the text', True), ('Explain every main point in full', False)])}, 'The main points come in the body.'),
            ('fill_blank', '"Preach the ___." (2 Timothy 4:2)', {'accepted_answers': 'word\nthe word'}, '2 Timothy 4:2.'),
            ('matching', 'Match each term to its meaning.', {'option_ids': pairs_([('Exegesis', 'Finding what the text meant'), ('Application', 'How the truth applies today'), ('Big idea', 'The one main truth of the sermon')])}, 'They work together.'),
            ('ordering', 'Put the steps of preparing a sermon in order.', {'option_ids': order_(['Choose the text', 'Study the text', 'State the big idea', 'Build the outline'])}, 'Text first, outline last.'),
        ]),
        'deck': ('Preaching Key Terms', [
            ('Homiletics', 'The art and science of preparing and preaching sermons.'),
            ('Exegesis', 'Drawing the meaning out of a text in its context.'),
            ('Eisegesis', 'Reading your own ideas into a text. To be avoided.'),
            ('Big idea', 'The one central truth the sermon is built to communicate.'),
            ('Application', 'Showing how the truth should change belief and life today.'),
        ]),
    },
}


def build_course(course, plan):
    Content = env['college.course.content']
    Module = env['college.course.module']
    modules = []
    for number, (module_name, readings) in enumerate(plan['modules'], start=1):
        module = Module.create({'course_id': course.id, 'name': module_name, 'sequence': number})
        for seq, (title, body) in enumerate(readings, start=1):
            Content.create({'module_id': module.id, 'sequence': seq * 10, 'name': title, 'content_type': 'text', 'body': body})
        modules.append(module)
    quiz_name, questions = plan['quiz']
    quiz = env['college.quiz'].create({'name': quiz_name, 'pass_score': 60.0, 'shuffle_answers': True,
                                      'description': 'Six questions, one of each kind.'})
    for seq, (kind, text, vals, why) in enumerate(questions, start=1):
        env['college.quiz.question'].create(dict(vals, quiz_id=quiz.id, sequence=seq, question_type=kind, text=text, explanation=why))
    deck_name, cards = plan['deck']
    deck = env['college.flashcard.deck'].create({
        'name': deck_name, 'card_ids': [(0, 0, {'front': f, 'back': b, 'sequence': i}) for i, (f, b) in enumerate(cards)]})
    last = modules[-1]
    Content.create({'module_id': modules[0].id, 'sequence': 90, 'name': 'Flashcards: %s' % deck_name, 'content_type': 'flashcards', 'deck_id': deck.id})
    Content.create({'module_id': last.id, 'sequence': 95, 'name': 'Quiz: %s' % quiz_name, 'content_type': 'quiz', 'quiz_id': quiz.id})
    return modules


def right_answer(question):
    return question._grade(None)[2]  # the grader's own idea of the right answer


def answers_for(quiz, wrong=()):
    """Correct answers, except for the question numbers (1-based) in `wrong`."""
    answers = {}
    for number, question in enumerate(quiz.question_ids, start=1):
        answer = right_answer(question)
        if number in wrong:
            kind = question.question_type
            if kind == 'true_false':
                answer = not answer
            elif kind == 'single':
                answer = (question.option_ids.filtered(lambda o: not o.is_correct)[:1]).id
            elif kind == 'multiple':
                answer = answer[:1]  # part marks
            elif kind == 'fill_blank':
                answer = 'not sure'
            elif kind == 'matching':
                values = list(answer.values())
                answer = dict(zip(answer, values[1:] + values[:1]))  # every pair shifted
            elif kind == 'ordering':
                answer = answer[1:2] + answer[:1] + answer[2:]  # first two swapped
        answers[str(question.id)] = answer
    return answers


if Params.get_param(PARAM):
    print('The lesson activity is already there. Nothing was added.')
elif not Params.get_param(BASE_PARAM):
    print('Run sample_data.py first: this adds lessons and activity for its courses and students.')
else:
    before = {m: (env[m].search([], order='id desc', limit=1).id or 0) for m in MODELS}

    Course = env['college.course']
    built = []
    for name, plan in COURSES.items():
        course = Course.search([('name', '=', name)], limit=1)
        if course and not course.module_ids:
            build_course(course, plan)
            built.append(name)
    # The Old Testament Survey lessons sample_data.py made had no module;
    # file them under the course's first module so staff can reach them.
    ot = Course.search([('name', '=', 'Old Testament Survey')], limit=1)
    if ot and ot.module_ids:
        first = ot.module_ids.sorted('sequence')[:1]
        env['college.course.content'].search([('course_id', '=', ot.id), ('module_id', '=', False)]).write({'module_id': first.id})

    # ── Study activity, through the app's own calls ──
    Student = env['college.student']
    Session = env['college.student.session']
    Progress = env['college.lesson.progress']
    Quiz = env['college.quiz']
    Deck = env['college.flashcard.deck']
    VQ = env['college.video.question']

    def student(name):
        return Student.search([('name', '=', name)], limit=1)

    def lessons(course_name):
        course = Course.search([('name', '=', course_name)], limit=1)
        return course.content_ids.sorted(lambda c: (c.module_id.sequence or 0, c.sequence, c.id)) if course else env['college.course.content']

    def study(person, course_name, finish=1.0, wrong=(), watch=None, video_answers='right'):
        """Works through a share of a course's lessons the way the app would."""
        if not person or course_name not in person.enrollment_ids.course_id.mapped('name'):
            return
        token = Session._issue(person)
        todo = lessons(course_name)
        todo = todo[:max(1, round(len(todo) * finish))] if finish < 1 else todo
        for lesson in todo:
            kind = lesson.content_type
            if kind == 'quiz' and lesson.quiz_id:
                Quiz.app_college_my_quiz_submit(token, lesson.id, answers=answers_for(lesson.quiz_id, wrong))
            elif kind == 'flashcards' and lesson.deck_id:
                for card in lesson.deck_id.card_ids:
                    Deck.app_college_my_flashcard_mark(token, lesson.id, card.id, True)
            elif kind == 'video':
                pieces, length = watch or ('0-%d' % 10, 1241)
                Progress.app_college_my_progress_save(token, lesson.id, video_position=60, watched=pieces, duration=length)
                for question in lesson.video_question_ids.filtered('option_ids'):
                    pick = question.option_ids.filtered('is_correct')[:1] if video_answers == 'right' else question.option_ids.filtered(lambda o: not o.is_correct)[:1]
                    if pick:
                        VQ.app_college_my_video_answer(token, question.id, pick.id)
            else:
                Progress.app_college_my_progress_save(token, lesson.id, completed=True)
        return person

    sarah, daniel, naomi, joshua, esther, samuel = (student(n) for n in (
        'Sarah Masih', 'Daniel Gill', 'Naomi Bhatti', 'Joshua Sadiq', 'Esther Yousaf', 'Samuel Javed'))
    # A 20:41 video is 249 five-second pieces.
    study(sarah, 'New Testament Survey')                                  # finishes it: certificate
    study(sarah, 'Homiletics', finish=0.5, wrong=(3, 5))
    study(daniel, 'Old Testament Survey', finish=0.8, wrong=(2, 5, 6), watch=('0-150', 1241), video_answers='wrong')
    study(daniel, 'New Testament Survey', finish=0.6, wrong=(1, 4))
    study(daniel, 'Homiletics', finish=0.4)
    study(naomi, 'Old Testament Survey', watch=('0-248', 1241))           # finishes it
    study(naomi, 'Systematic Theology')                                   # finishes it: certificate
    study(naomi, 'Homiletics', finish=0.7, wrong=(5,))
    study(joshua, 'Old Testament Survey', finish=0.3, watch=('0-40', 1241), video_answers='wrong')
    study(samuel, 'Pastoral Care', finish=0.6, wrong=(3, 6))
    # Esther (New Testament Survey) has not started, so she shows as falling behind.

    # Certificates for every finished course, the way the app issues them.
    Certificate = env['college.certificate']
    for person in (sarah, naomi):
        if not person:
            continue
        for enrollment in person.enrollment_ids:
            total, done = Certificate._enrollment_progress(enrollment)
            if total and done >= total:
                Certificate._issue(person, enrollment)

    env.flush_all()
    # Joshua last studied three weeks ago: he shows as falling behind too.
    if joshua:
        env.cr.execute("UPDATE college_lesson_progress SET write_date = now() - interval '21 days' WHERE student_id = %s", [joshua.id])

    created = {m: env[m].search([('id', '>', before[m])]).ids for m in MODELS}
    # The temporary sign-ins were only for making the activity.
    Session.browse(created['college.student.session']).write({'revoked': True})
    Params.set_param(PARAM, json.dumps(created))
    env.cr.commit()

    print('Lessons added to: %s' % (', '.join(built) or 'no course (they all had modules already)'))
    print('Added %d quizzes, %d flashcard decks, %d quiz attempts, %d lessons of progress, %d badges, %d certificates.' % (
        len(created['college.quiz']), len(created['college.flashcard.deck']), len(created['college.quiz.attempt']),
        len(created['college.lesson.progress']), len(created['college.badge.award']), len(created['college.certificate'])))
