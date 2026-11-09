"""Urdu versions of the example course content (sample_data.py,
lms_sample_data.py, and the quiz, flashcards and video questions added for
"Who Really Wrote the Bible?"), so the app's اردو switch shows Urdu content.

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db --no-http \
        < /path/to/revive_bible_college/scripts/sample_data_urdu.py

Each record is found by its English text, so it works on any database and
leaves everything else alone. Bible verses are quoted word for word from the
Urdu Geo Version (2019), the Urdu Bible already in the app. Running it again
just writes the same Urdu again. Staff can change any of it in the ERP with
the language button next to each field.
"""
import re

UR = 'ur_PK'
env = env(su=True)
env['college.course']._ensure_urdu_language()


def norm(text):
    return re.sub(r'\s+', ' ', (text or '').strip().rstrip('.').strip()).casefold()


# ── Names (and descriptions / bodies) by English name ───────────────
PROGRAMS = {
    'Diploma in Theology': 'الہیات میں ڈپلوما',
    'Certificate in Biblical Studies': 'بائبل مطالعہ میں سرٹیفکیٹ',
    'Bachelor of Divinity': 'بیچلر آف ڈیوینیٹی',
}
TERMS = {'Fall 2026': 'خزاں 2026', 'Spring 2027': 'بہار 2027'}
COURSES = {
    'Old Testament Survey': 'عہدِ عتیق کا جائزہ',
    'New Testament Survey': 'عہدِ جدید کا جائزہ',
    'Homiletics': 'وعظ گوئی',
    'Systematic Theology': 'منظم الہیات',
    'Church History': 'کلیسیا کی تاریخ',
    'Pastoral Care': 'پاسبانی نگہداشت',
}
MODULES = {
    'The Pentateuch': 'توریت کی پانچ کتابیں',
    'The Prophets': 'انبیا',
    'The Gospels': 'اناجیل',
    'Acts and the Letters': 'اعمال اور خطوط',
    'Knowing God': 'خدا کی پہچان',
    'Salvation': 'نجات',
    'The Early Church': 'ابتدائی کلیسیا',
    'The Reformation': 'اصلاحِ کلیسیا',
    'Caring for People': 'لوگوں کی نگہداشت',
    'Foundations of Preaching': 'منادی کی بنیادیں',
    'Preparing the Sermon': 'وعظ کی تیاری',
    'Delivering the Sermon': 'وعظ پیش کرنا',
    'Course Materials': 'کورس کا مواد',
}
# Lessons: English name -> (Urdu name, Urdu body or None)
LESSONS = {
    'Course syllabus': ('کورس کا خاکہ', None),
    'Who Really Wrote the Bible?': ('بائبل اصل میں کس نے لکھی؟', None),
    'Reading: Genesis overview': ('مطالعہ: پیدایش کا جائزہ',
        'پیدایش پوری بائبل کی بنیاد رکھتی ہے: تخلیق، انسان کا گناہ میں گرنا، عہد اور بنی اسرائیل کا آغاز۔ '
        'باب 12، 15 اور 17 میں عہد پر خاص توجہ دیں۔'),
    'Parallel Bible reader': ('متوازی بائبل', None),
    'Quiz: Who Wrote the Bible?': ('کوئز: بائبل کس نے لکھی؟', None),
    'Flashcards: Who Wrote the Bible?': ('یادداشتی کارڈ: بائبل کس نے لکھی؟', None),
    # Old Testament Survey
    'The Five Books of Moses': ('موسیٰ کی پانچ کتابیں',
        'پیدایش، خروج، احبار، گنتی اور استثنا کو توریت کہا جاتا ہے۔ یہ بتاتی ہیں کہ اللہ نے دنیا کو کیسے بنایا، '
        'ابراہیم کو بُلایا، بنی اسرائیل کو مصر سے رِہائی دی اور کوہِ سینا پر شریعت عطا کی۔\n\n'
        'انہیں ایک ہی کہانی کے طور پر پڑھیں: وعدہ (پیدایش)، رِہائی (خروج)، پاکیزگی (احبار)، بیابان میں آزمائش (گنتی) '
        'اور عہد کی تجدید (استثنا)۔'),
    'Covenant in Genesis': ('پیدایش میں عہد',
        'پیدایش 12، 15 اور 17 میں ابراہیم کے ساتھ اللہ کا عہد زمین، نسل اور تمام قوموں کے لئے برکت کا وعدہ کرتا ہے۔ '
        'باقی ساری بائبل دکھاتی ہے کہ اللہ یہ وعدہ کیسے پورا کرتا ہے۔\n\n'
        'غور کریں کہ یہ عہد اللہ کی وفاداری پر قائم ہے: پیدایش 15 میں صرف اللہ ہی ٹکڑوں کے درمیان سے گزرتا ہے۔'),
    'Major and Minor Prophets': ('بڑے اور چھوٹے انبیا',
        '"بڑے" انبیا (یسعیاہ، یرمیاہ، حزقی ایل، دانی ایل) کی کتابیں لمبی ہیں، زیادہ اہم نہیں۔ ہوسیع سے ملاکی تک '
        'بارہ "چھوٹے" انبیا کی کتابیں مختصر ہیں۔\n\n'
        'انبیا نے بنی اسرائیل کو عہد کی طرف واپس بُلایا، عدالت سے خبردار کیا اور آنے والے مسیح کا وعدہ دیا '
        '(یسعیاہ 53، میکاہ 5:2)۔'),
    # New Testament Survey
    'Four Gospels, One Jesus': ('چار اناجیل، ایک عیسیٰ',
        'متی، مرقس اور لوقا کو متوافق اناجیل کہا جاتا ہے کیونکہ ان کا بہت سا مواد مشترک ہے۔ یوحنا مختلف انداز میں '
        'لکھتا ہے، لمبی گفتگو اور سات معجزانہ نشانوں کے ساتھ۔\n\n'
        'متی یہودی قارئین کے لئے لکھتا ہے، مرقس واقعات پر زور دیتا ہے، لوقا ایک محتاط مؤرخ کی طرح لکھتا ہے، اور یوحنا '
        'اِس لئے لکھتا ہے "کہ آپ ایمان لائیں کہ عیسیٰ ہی مسیح یعنی اللہ کا فرزند ہے" (یوحنا 20:31)۔'),
    'The Kingdom of God': ('اللہ کی بادشاہی',
        'عیسیٰ نے اپنی منادی اِن الفاظ سے شروع کی: "مقررہ وقت آ گیا ہے، اللہ کی بادشاہی قریب آ گئی ہے۔ توبہ کرو اور '
        'اللہ کی خوش خبری پر ایمان لاؤ" (مرقس 1:15)۔ بادشاہی اللہ کی حکمرانی ہے، جو عیسیٰ میں آ چکی ہے اور '
        'جس کی تکمیل ابھی آنی ہے۔\n\nمتی 13 کی تمثیلیں دکھاتی ہیں کہ بادشاہی چھوٹی سی ابتدا سے بڑھتی ہے۔'),
    "Paul's Missionary Journeys": ('پولُس کے تبلیغی سفر',
        'اعمال کی کتاب خوش خبری کو یروشلم سے روم تک پہنچتے دکھاتی ہے (اعمال 1:8)۔ پولُس نے تین تبلیغی سفر کئے اور '
        'ایشیائے کوچک اور یونان میں کلیسیائیں قائم کیں، پھر قیدی کی حیثیت سے روم گیا۔\n\nاُس کے بہت سے خطوط انہی '
        'کلیسیاؤں کو لکھے گئے: گلتیوں، تھسلنیکیوں، کرنتھیوں، فلپیوں اور افسیوں۔'),
    # Systematic Theology
    'Revelation': ('مکاشفہ',
        'اللہ دو طریقوں سے اپنے آپ کو ظاہر کرتا ہے۔ عام مکاشفہ وہ ہے جو سب لوگ تخلیق اور ضمیر میں اللہ کے بارے '
        'میں دیکھ سکتے ہیں (زبور 19:1، رومیوں 1:20)۔ خاص مکاشفہ اللہ کا کلام ہے، جو پاک نوشتوں میں لکھا گیا اور '
        'عیسیٰ مسیح میں مجسم ہوا (عبرانیوں 1:1-2)۔\n\nعام مکاشفہ ہمیں بےعذر چھوڑتا ہے؛ نجات کا راستہ صرف خاص '
        'مکاشفہ بتاتا ہے۔'),
    'The Trinity': ('تثلیث',
        'اللہ ایک ہے (استثنا 6:4) جو ازل سے تین اقانیم میں موجود ہے: باپ، فرزند اور روح القدس (متی 28:19)۔ '
        'تینوں پورے طور پر خدا ہیں، اور وہ تین خدا نہیں ہیں۔\n\nلفظ "تثلیث" بائبل میں نہیں، لیکن یہ بائبل کی '
        'تعلیم کا خلاصہ ہے۔'),
    'Justification by Faith': ('ایمان سے راست بازی',
        'راست باز ٹھہرائے جانے کا مطلب ہے کہ اللہ کسی کو راست باز قرار دے۔ پولُس سکھاتا ہے کہ "انسان کو ایمان سے '
        'راست باز ٹھہرایا جاتا ہے، نہ کہ اعمال سے" (رومیوں 3:28)، کیونکہ مسیح کی راست بازی ایمان دار کے حساب '
        'میں شمار ہوتی ہے۔\n\nنیک اعمال راست بازی نہیں کماتے؛ وہ اُس کے نتیجے میں آتے ہیں (افسیوں 2:8-10)۔'),
    # Church History
    'Persecution and Growth': ('ایذا رسانی اور ترقی',
        'تقریباً تین صدیوں تک مسیحیوں کو رومی شہنشاہوں کے دور میں بار بار ایذا کا سامنا رہا۔ پھر بھی کلیسیا بڑھتی '
        'رہی: ترتلیان نے لکھا کہ شہیدوں کا خون بیج ہے۔\n\n313 میں فرمانِ میلان نے مسیحیوں کو عبادت کی قانونی '
        'آزادی دی۔'),
    'The Council of Nicaea': ('نیقیہ کی کونسل',
        '325 میں پہلی عالمی کلیسیائی کونسل نیقیہ میں جمع ہوئی تاکہ آریوس کو جواب دے، جو سکھاتا تھا کہ فرزند ایک '
        'مخلوق ہے۔ کونسل نے اقرار کیا کہ فرزند "باپ کے ساتھ ایک ہی جوہر" ہے۔\n\nنیقیہ کا عقیدہ آج بھی بہت سی '
        'کلیسیاؤں میں پڑھا جاتا ہے۔'),
    'The Protestant Reformation': ('پروٹسٹنٹ اصلاحِ کلیسیا',
        '31 اکتوبر 1517 کو مارٹن لوتھر نے وِٹن برگ میں اپنے پچانوے نکات لگائے۔ اِس کے بعد آنے والی اصلاح کو اکثر '
        'پانچ "صرف" میں بیان کیا جاتا ہے: صرف پاک کلام، صرف فضل، صرف ایمان، صرف مسیح، اور صرف اللہ کا جلال۔\n\n'
        'دوسرے مصلحین میں زونگلی، کیلون اور ناکس شامل تھے۔'),
    # Pastoral Care
    'Listening Well': ('اچھی طرح سننا',
        'یعقوب 1:19 کہتا ہے: "ہر شخص سننے میں تیز ہو، لیکن بولنے اور غصہ کرنے میں دھیما۔" اچھی پاسبانی نگہداشت '
        'سننے سے شروع ہوتی ہے: پوری توجہ دینا، کھلے سوال پوچھنا اور جواب دینے میں جلدی نہ کرنا۔\n\nدکھ میں پڑے '
        'لوگوں کو اکثر وضاحت سے زیادہ ساتھ کی ضرورت ہوتی ہے۔ ایوب کے دوستوں نے پہلے سات دنوں میں سب سے اچھا کیا، '
        'جب وہ خاموشی سے اُس کے ساتھ بیٹھے رہے (ایوب 2:13)۔'),
    'Visiting the Sick': ('بیماروں کی عیادت',
        'عیسیٰ نے فرمایا: "مَیں بیمار تھا اور تم نے میری دیکھ بھال کی" (متی 25:36)۔ ہسپتال کی ملاقات مختصر رکھیں، '
        'ہاتھ دھوئیں، مریض کی رازداری کا احترام کریں اور دعا سے پہلے اجازت لیں۔\n\nکوئی مختصر زبور پڑھیں، جیسے '
        'زبور 23 یا 121، اور مریض کو اُمید کی بات کے ساتھ چھوڑیں۔'),
    # Homiletics (both the full version and the shorter one)
    'What Is Homiletics?': ('وعظ گوئی کیا ہے؟',
        'وعظ گوئی وعظ تیار کرنے اور پیش کرنے کا فن اور علم ہے۔ یہ تفسیر کے اصولوں کے ساتھ ساتھ چلتی ہے: تفسیر '
        'پوچھتی ہے کہ اِس حوالے کا مطلب کیا ہے؛ وعظ گوئی پوچھتی ہے کہ میں یہ مطلب آج اِن سننے والوں تک وفاداری سے '
        'کیسے پہنچاؤں۔\n\nاچھا وعظ متن کا وفادار، اپنے مرکزی خیال میں واضح، ترتیب میں آسان، اور عملی ہوتا ہے، '
        'تاکہ سننے والے جانیں کہ اللہ اُنہیں کیا ماننے اور کیا کرنے کو کہہ رہا ہے۔'),
    "The Preacher's Calling": ('مُناد کی بُلاہٹ',
        '"وقت بےوقت کلامِ مُقدّس کی منادی کرنے کے لئے تیار رہیں۔ بڑے صبر سے ایمان داروں کو تعلیم دے کر اُنہیں '
        'سمجھائیں، ملامت کریں اور اُن کی حوصلہ افزائی بھی کریں۔" (۲-تیمُتھیُس 4:2)\n\nتیمُتھیُس کو پولُس کی یہ '
        'ہدایت دکھاتی ہے کہ منادی پہلے ایک بُلاہٹ ہے، کوئی نمائش نہیں۔ مُناد کلام کا خادم ہے، اُس کا مالک نہیں: '
        'پیغام پاک کلام سے آتا ہے، مُناد کی رائے سے نہیں۔\n\nرومیوں 10:14 پوچھتا ہے کہ وہ کس طرح سن سکتے ہیں '
        'اگر کسی نے اُنہیں پیغام سنایا نہیں۔ منادی لوگوں کو ایمان تک لانے کا اللہ کا چُنا ہوا طریقہ ہے۔ اِسی لئے '
        'مُناد کی اپنی دعا، مطالعہ اور فرماں برداری کسی بھی طریقے جتنی اہم ہے۔'),
    'Choosing and Studying the Text': ('متن کا انتخاب اور مطالعہ',
        'کسی حوالے سے شروع کریں، کسی ایسے موضوع سے نہیں جسے آپ ثابت کرنا چاہتے ہیں۔ کوئی مکمل حصہ چُنیں، جیسے '
        'ایک پیراگراف، ایک واقعہ یا ایک زبور، نہ کہ اپنے سیاق سے کٹی ہوئی ایک آیت۔\n\nمتن کی تشریح کا مطلب ہے '
        'متن سے اُس کا مطلب نکالنا: اُسے سیاق و سباق میں پڑھیں، پوچھیں کہ کس نے، کس کو اور کیوں لکھا، اہم الفاظ '
        'نوٹ کریں اور دوسرے ترجموں سے موازنہ کریں۔ اپنے خیالات متن میں ڈالنے سے بچیں۔\n\nتین سوال پوچھیں: پہلے '
        'قارئین کے لئے اِس کا مطلب کیا تھا؟ یہ کون سی ابدی سچائی سکھاتا ہے؟ یہ سچائی آج میرے سننے والوں پر کیسے '
        'لاگو ہوتی ہے؟'),
    'The Big Idea and the Outline': ('مرکزی خیال اور خاکہ',
        'ہر وعظ کو اپنا مرکزی نکتہ ایک واضح جملے میں بیان کرنے کے قابل ہونا چاہئے: یہی مرکزی خیال ہے۔ اگر آپ '
        'اِسے سادہ الفاظ میں نہیں کہہ سکتے تو جماعت بھی اِسے یاد نہیں رکھ سکے گی۔\n\nپھر ایسا خاکہ بنائیں جو مرکزی '
        'خیال کی خدمت کرے:\n1. تمہید: توجہ حاصل کریں، متن کا تعارف دیں، دکھائیں کہ یہ کیوں اہم ہے۔\n2. مرکزی '
        'نکات: عموماً دو سے چار، ہر ایک متن سے۔\n3. اختتام: مرکزی خیال دہرائیں اور ردِ عمل کی دعوت دیں۔\n\nہر '
        'مرکزی نکتہ متن کی وضاحت کرے، مثال دے اور اُسے عملی زندگی پر لاگو کرے۔'),
    'Illustrations and Application': ('مثالیں اور عملی اطلاق',
        'مثال کوئی کہانی، تصویر یا نمونہ ہے جو کسی سچائی کو واضح کرے۔ عیسیٰ نے بیج، سِکّے، بھیڑیں اور چراغ استعمال '
        'کئے۔ اچھی مثالیں مختصر، حقیقی زندگی جیسی ہوتی ہیں اور نکتے کی خدمت کرتی ہیں، اُس سے توجہ نہیں ہٹاتیں۔\n\n'
        'عملی اطلاق اِس سوال کا جواب ہے: "تو پھر؟" یہ دکھاتا ہے کہ اِس ہفتے سچائی کو سننے والوں کے ایمان، احساس '
        'اور کاموں کو کیسے بدلنا چاہئے۔ اِسے مخصوص بنائیں: جوانوں اور بزرگوں کے لئے، گھر میں، کام پر، کلیسیا میں۔'
        '\n\nعملی اطلاق کے بغیر وعظ ذہن کو معلومات دیتا ہے لیکن زندگی کو نہیں بدلتا۔'),
    'Delivering the Sermon': ('وعظ پیش کرنا',
        'پیش کرنے کا انداز پیغام کو لے کر چلتا ہے۔ صاف بولیں اور اتنی آواز سے کہ پیچھے تک سنائی دے۔ رفتار اور لہجہ '
        'بدلتے رہیں، اور اہم باتوں کے بعد ٹھہریں۔\n\nجماعت سے نظریں ملائیں؛ نوٹس کو رہنمائی کے لئے استعمال کریں، '
        'پڑھنے کے لئے نہیں۔ اشارے فطری ہوں۔\n\nوقت کا احترام کریں۔ پچیس منٹ کا مرکوز وعظ عموماً ایک گھنٹے کے '
        'بھٹکتے وعظ سے زیادہ پھل لاتا ہے۔ پہلے سے بلند آواز میں مشق کریں، اور منادی سے پہلے دعا کریں: کلام کو '
        'مؤثر روح القدس بناتا ہے، فصاحت نہیں۔'),
}

QUIZZES = {
    'Who Wrote the Bible? Quiz': ('کوئز: بائبل کس نے لکھی؟', 'بائبل کیسے لکھی گئی، اِس بارے میں چھ مختصر سوال۔'),
    'Building a Sermon': ('وعظ کی تعمیر', 'وعظ کی تیاری کے بارے میں چھ سوال۔'),
    'The Pentateuch': ('توریت کی پانچ کتابیں', 'چھ سوال، ہر قسم کا ایک۔'),
    'Gospels and Acts': ('اناجیل اور اعمال', 'چھ سوال، ہر قسم کا ایک۔'),
    'Core Doctrines': ('بنیادی عقائد', 'چھ سوال، ہر قسم کا ایک۔'),
    'Church History Milestones': ('کلیسیا کی تاریخ کے سنگِ میل', 'چھ سوال، ہر قسم کا ایک۔'),
    'Pastoral Care Basics': ('پاسبانی نگہداشت کی بنیادی باتیں', 'چھ سوال، ہر قسم کا ایک۔'),
}

# Quiz questions by English text: Urdu text, explanation, accepted answers,
# and the answers by their English text (or (item, matches) for matching).
QUESTIONS = {
    # Who Wrote the Bible? Quiz
    'The Bible was written by one person in a single lifetime.': {
        'text': 'بائبل ایک ہی شخص نے اپنی ایک زندگی میں لکھی۔',
        'explanation': 'اِسے تقریباً 40 لکھنے والوں نے تقریباً 1,500 سال میں لکھا۔'},
    'Which verse says "All Scripture is given by inspiration of God"?': {
        'text': 'کون سی آیت کہتی ہے: "ہر پاک نوشتہ اللہ کے روح سے وجود میں آیا ہے"؟',
        'explanation': '۲-تیمُتھیُس 3:16۔',
        'options': {'John 3:16': 'یوحنا 3:16', '2 Timothy 3:16': '۲-تیمُتھیُس 3:16', 'Romans 8:28': 'رومیوں 8:28', 'Psalm 23:1': 'زبور 23:1'}},
    'Which of these people wrote books of the Bible? Choose all that apply.': {
        'text': 'اِن میں سے کن لوگوں نے بائبل کی کتابیں لکھیں؟ تمام درست جوابات منتخب کریں۔',
        'explanation': 'موسیٰ، داؤد اور پولُس نے پاک کلام لکھا۔ مارٹن لوتھر بائبل مکمل ہونے کے تقریباً 1,400 سال بعد پیدا ہوا۔',
        'options': {'Moses': 'موسیٰ', 'David': 'داؤد', 'Paul': 'پولُس', 'Martin Luther': 'مارٹن لوتھر'}},
    'Fill in the blank: "Holy men of God spake as they were moved by the Holy ___." (2 Peter 1:21)': {
        'text': 'خالی جگہ پُر کریں: "انسانوں نے ___ سے تحریک پا کر اللہ کی طرف سے بات کی۔" (۲-پطرس 1:21)',
        'accepted': 'روح القدس\nروح',
        'explanation': '۲-پطرس 1:21: "پیش گوئی کرتے وقت انسانوں نے روح القدس سے تحریک پا کر اللہ کی طرف سے بات کی۔"'},
    'Match each book to the person who wrote it.': {
        'text': 'ہر کتاب کو اُس کے لکھنے والے سے ملائیں۔',
        'explanation': 'پیدایش: موسیٰ۔ زبور: زیادہ تر داؤد۔ رومیوں: پولُس۔ مکاشفہ: یوحنا۔',
        'options': {'Genesis': ('پیدایش', 'موسیٰ'), 'Most of the Psalms': ('زبور کا زیادہ تر حصہ', 'داؤد'),
                    'Romans': ('رومیوں', 'پولُس'), 'Revelation': ('مکاشفہ', 'یوحنا')}},
    'Put these books in the order they appear in the Bible.': {
        'text': 'اِن کتابوں کو بائبل میں اُن کی ترتیب سے لگائیں۔',
        'explanation': 'پیدایش عہدِ عتیق کا آغاز ہے، زبور اُس کے درمیان، متی عہدِ جدید کا آغاز اور مکاشفہ آخری کتاب ہے۔',
        'options': {'Genesis': 'پیدایش', 'Psalms': 'زبور', 'Matthew': 'متی', 'Revelation': 'مکاشفہ'}},
    # Building a Sermon (both versions)
    'Exegesis means reading your own ideas into the text.': {
        'text': 'متن کی تشریح کا مطلب ہے اپنے خیالات متن میں ڈالنا۔',
        'explanation': 'وہ غلط تشریح ہے۔ درست تشریح متن سے اُس کا مطلب نکالتی ہے۔'},
    'What is homiletics?': {
        'text': 'وعظ گوئی کیا ہے؟',
        'explanation': 'وعظ گوئی وعظ تیار کرنے اور پیش کرنے کا فن اور علم ہے۔',
        'options': {'The art and science of preaching': 'منادی کا فن اور علم', 'The study of hymns': 'حمدوں کا مطالعہ',
                    'Church history': 'کلیسیا کی تاریخ', 'The study of Bible languages': 'بائبل کی زبانوں کا مطالعہ'}},
    "Which of these belong in a sermon's introduction? Choose all that apply.": {
        'text': 'اِن میں سے کون سی باتیں وعظ کی تمہید میں آتی ہیں؟ تمام درست جوابات منتخب کریں۔',
        'explanation': 'تمہید سننے والوں کو تیار کرتی ہے؛ مرکزی نکات وعظ کے درمیان میں آتے ہیں۔',
        'options': {'Gain attention': 'توجہ حاصل کریں', 'Introduce the text': 'متن کا تعارف دیں',
                    'Show why it matters': 'دکھائیں کہ یہ کیوں اہم ہے', 'Explain every main point in full': 'ہر مرکزی نکتہ پوری تفصیل سے بیان کریں'}},
    'Fill in the blank: "Preach the ___; be instant in season, out of season." (2 Timothy 4:2)': {
        'text': 'خالی جگہ پُر کریں: "وقت بےوقت ___ کی منادی کرنے کے لئے تیار رہیں۔" (۲-تیمُتھیُس 4:2)',
        'accepted': 'کلامِ مُقدّس\nکلام',
        'explanation': '۲-تیمُتھیُس 4:2: "وقت بےوقت کلامِ مُقدّس کی منادی کرنے کے لئے تیار رہیں۔"'},
    '"Preach the ___." (2 Timothy 4:2)': {
        'text': '"___ کی منادی کرنے کے لئے تیار رہیں۔" (۲-تیمُتھیُس 4:2)',
        'accepted': 'کلامِ مُقدّس\nکلام', 'explanation': '۲-تیمُتھیُس 4:2۔'},
    'Match each term to its meaning.': {
        'text': 'ہر اصطلاح کو اُس کے مطلب سے ملائیں۔',
        'explanation': 'یہ سب مل کر کام کرتے ہیں۔',
        'options': {'Exegesis': ('تشریح', 'متن کا اصل مطلب معلوم کرنا'),
                    'Illustration': ('مثال', 'ایک کہانی جو نکتہ واضح کرے'),
                    'Application': ('عملی اطلاق', 'سچائی آج کیسے لاگو ہوتی ہے'),
                    'Big idea': ('مرکزی خیال', 'وعظ کی ایک مرکزی سچائی'),
                    'Justification': ('راست بازی', 'راست باز قرار دیا جانا'),
                    'Sanctification': ('تقدیس', 'وقت کے ساتھ پاک بنایا جانا'),
                    'Glorification': ('جلال', 'جلال میں کامل بنایا جانا')}},
    'Put the steps of preparing a sermon in order.': {
        'text': 'وعظ کی تیاری کے مراحل ترتیب سے لگائیں۔',
        'explanation': 'پہلے متن، پھر مطلب، پھر مرکزی خیال، پھر ترتیب، پھر مثالیں اور عملی اطلاق۔',
        'options': {'Choose the text': 'متن چُنیں', 'Study the text': 'متن کا مطالعہ کریں', 'State the big idea': 'مرکزی خیال بیان کریں',
                    'Build the outline': 'خاکہ بنائیں', 'Add illustrations and application': 'مثالیں اور عملی اطلاق شامل کریں'}},
    # The Pentateuch quiz
    'Deuteronomy is one of the five books of Moses.': {
        'text': 'استثنا موسیٰ کی پانچ کتابوں میں سے ایک ہے۔', 'explanation': 'توریت پیدایش سے استثنا تک ہے۔'},
    'In which book does God give the Ten Commandments?': {
        'text': 'اللہ کس کتاب میں دس احکام دیتا ہے؟', 'explanation': 'خروج 20۔',
        'options': {'Genesis': 'پیدایش', 'Exodus': 'خروج', 'Leviticus': 'احبار', 'Numbers': 'گنتی'}},
    'Which of these are major prophets? Choose all that apply.': {
        'text': 'اِن میں سے کون بڑے انبیا ہیں؟ تمام درست جوابات منتخب کریں۔',
        'explanation': 'عاموس بارہ چھوٹے انبیا میں سے ایک ہے۔',
        'options': {'Isaiah': 'یسعیاہ', 'Jeremiah': 'یرمیاہ', 'Amos': 'عاموس', 'Ezekiel': 'حزقی ایل'}},
    'Fill in the blank: "In the beginning God created the heaven and the ___." (Genesis 1:1)': {
        'text': 'خالی جگہ پُر کریں: "ابتدا میں اللہ نے آسمان اور ___ کو بنایا۔" (پیدایش 1:1)',
        'accepted': 'زمین', 'explanation': 'پیدایش 1:1۔'},
    'Match each book to what it is known for.': {
        'text': 'ہر کتاب کو اُس بات سے ملائیں جس کے لئے وہ مشہور ہے۔',
        'explanation': 'ہر کتاب کہانی کو ایک قدم آگے بڑھاتی ہے۔',
        'options': {'Genesis': ('پیدایش', 'ابتدا'), 'Exodus': ('خروج', 'مصر سے رِہائی'),
                    'Leviticus': ('احبار', 'پاکیزگی اور قربانی'), 'Numbers': ('گنتی', 'بیابان کے سال')}},
    'Put these in the order they happen in Genesis.': {
        'text': 'اِنہیں اُس ترتیب سے لگائیں جس میں یہ پیدایش میں ہوتے ہیں۔',
        'explanation': 'پیدایش 1، 6 تا 9، 12 اور 37 تا 50۔',
        'options': {'Creation': 'تخلیق', 'The flood': 'طوفانِ نوح', 'The call of Abraham': 'ابراہیم کی بُلاہٹ', 'Joseph in Egypt': 'مصر میں یوسف'}},
    # Gospels and Acts
    'John is one of the synoptic Gospels.': {
        'text': 'یوحنا متوافق اناجیل میں سے ایک ہے۔', 'explanation': 'متوافق اناجیل متی، مرقس اور لوقا ہیں۔'},
    'Who wrote the book of Acts?': {
        'text': 'اعمال کی کتاب کس نے لکھی؟', 'explanation': 'لوقا نے اپنی انجیل اور اعمال دونوں لکھیں (اعمال 1:1)۔',
        'options': {'Peter': 'پطرس', 'Luke': 'لوقا', 'Paul': 'پولُس', 'John': 'یوحنا'}},
    'Which of these did Paul write? Choose all that apply.': {
        'text': 'اِن میں سے کون سے خطوط پولُس نے لکھے؟ تمام درست جوابات منتخب کریں۔',
        'explanation': 'عبرانیوں کے خط میں لکھنے والے کا نام نہیں۔',
        'options': {'Romans': 'رومیوں', 'Galatians': 'گلتیوں', 'Hebrews': 'عبرانیوں', 'Philippians': 'فلپیوں'}},
    'Fill in the blank: "For God so loved the ___." (John 3:16)': {
        'text': 'خالی جگہ پُر کریں: "کیونکہ اللہ نے ___ سے اِتنی محبت رکھی…" (یوحنا 3:16)',
        'accepted': 'دنیا', 'explanation': 'یوحنا 3:16۔'},
    'Match each Gospel to its main audience.': {
        'text': 'ہر انجیل کو اُس کے اصل قارئین سے ملائیں۔', 'explanation': 'متی 1:1، لوقا 1:3، یوحنا 20:31۔',
        'options': {'Matthew': ('متی', 'یہودی قارئین'), 'Luke': ('لوقا', 'تھیوفلس'), 'John': ('یوحنا', 'وہ سب جو ایمان لا سکیں')}},
    'Put these in the order of the New Testament.': {
        'text': 'اِنہیں عہدِ جدید کی ترتیب سے لگائیں۔', 'explanation': 'اناجیل، تاریخ، خطوط، نبوت۔',
        'options': {'Matthew': 'متی', 'Acts': 'اعمال', 'Romans': 'رومیوں', 'Revelation': 'مکاشفہ'}},
    # Core Doctrines
    'The word "Trinity" appears in the Bible.': {
        'text': 'لفظ "تثلیث" بائبل میں موجود ہے۔', 'explanation': 'لفظ موجود نہیں، لیکن تعلیم موجود ہے۔'},
    'What does "justified" mean?': {
        'text': '"راست باز ٹھہرایا جانا" کا کیا مطلب ہے؟', 'explanation': 'رومیوں 3:28، 5:1۔',
        'options': {'Made perfect in behaviour': 'رویے میں کامل بنایا جانا', 'Declared righteous by God': 'اللہ کی طرف سے راست باز قرار دیا جانا',
                    'Baptised': 'بپتسمہ پانا', 'Forgiven by the church': 'کلیسیا کی طرف سے معافی'}},
    'Which are persons of the Trinity? Choose all that apply.': {
        'text': 'تثلیث کے اقانیم کون سے ہیں؟ تمام درست جوابات منتخب کریں۔', 'explanation': 'متی 28:19۔',
        'options': {'The Father': 'باپ', 'The Son': 'فرزند', 'Mary': 'مریم', 'The Holy Spirit': 'روح القدس'}},
    'Revelation seen in creation and conscience is called ___ revelation.': {
        'text': 'تخلیق اور ضمیر میں دکھائی دینے والا مکاشفہ ___ مکاشفہ کہلاتا ہے۔',
        'accepted': 'عام', 'explanation': 'عام مکاشفہ (زبور 19:1، رومیوں 1:20)۔'},
    'Put these in the order of Romans 8:30.': {
        'text': 'اِنہیں رومیوں 8:30 کی ترتیب سے لگائیں۔',
        'explanation': '"جنہیں اُس نے پہلے سے مقرر کیا اُنہیں اُس نے بُلایا بھی…"',
        'options': {'Predestined': 'پہلے سے مقرر کیا', 'Called': 'بُلایا', 'Justified': 'راست باز ٹھہرایا', 'Glorified': 'جلال بخشا'}},
    # Church History Milestones
    'The Edict of Milan gave Christians freedom to worship.': {
        'text': 'فرمانِ میلان نے مسیحیوں کو عبادت کی آزادی دی۔', 'explanation': 'سنہ 313۔'},
    'In which year did Luther post the Ninety-five Theses?': {
        'text': 'لوتھر نے پچانوے نکات کس سال لگائے؟', 'explanation': '31 اکتوبر 1517۔',
        'options': {'1417': '1417', '1517': '1517', '1617': '1617', '1717': '1717'}},
    'Which of these were Protestant reformers? Choose all that apply.': {
        'text': 'اِن میں سے کون پروٹسٹنٹ مصلحین تھے؟ تمام درست جوابات منتخب کریں۔',
        'explanation': 'قسطنطین چوتھی صدی کے شروع کا رومی شہنشاہ تھا۔',
        'options': {'John Calvin': 'جان کیلون', 'Ulrich Zwingli': 'اُلرِخ زونگلی', 'Constantine': 'قسطنطین', 'John Knox': 'جان ناکس'}},
    'The council that met in AD 325 is the Council of ___.': {
        'text': 'سنہ 325 میں جمع ہونے والی کونسل ___ کی کونسل ہے۔', 'accepted': 'نیقیہ', 'explanation': 'نیقیہ کی کونسل۔'},
    'Match each person to what they are known for.': {
        'text': 'ہر شخص کو اُس بات سے ملائیں جس کے لئے وہ مشہور ہے۔',
        'explanation': 'نیقیہ نے آریوس کو جواب دیا؛ لوتھر نے اصلاحِ کلیسیا شروع کی۔',
        'options': {'Luther': ('لوتھر', 'پچانوے نکات'), 'Arius': ('آریوس', 'سکھایا کہ فرزند مخلوق ہے'),
                    'Constantine': ('قسطنطین', 'نیقیہ کی کونسل بُلائی')}},
    'Put these in order, earliest first.': {
        'text': 'اِنہیں ترتیب سے لگائیں، سب سے پہلے والا پہلے۔', 'explanation': '313، 325، 1517۔',
        'options': {'Edict of Milan (313)': 'فرمانِ میلان (313)', 'Council of Nicaea (325)': 'نیقیہ کی کونسل (325)',
                    'Ninety-five Theses (1517)': 'پچانوے نکات (1517)'}},
    # Pastoral Care Basics
    'A hospital visit should usually be short.': {
        'text': 'ہسپتال کی ملاقات عموماً مختصر ہونی چاہئے۔', 'explanation': 'بیمار لوگ جلد تھک جاتے ہیں۔'},
    'According to James 1:19, we should be...': {
        'text': 'یعقوب 1:19 کے مطابق ہمیں ہونا چاہئے…', 'explanation': '"ہر شخص سننے میں تیز ہو، لیکن بولنے اور غصہ کرنے میں دھیما۔"',
        'options': {'Swift to speak': 'بولنے میں تیز', 'Swift to hear': 'سننے میں تیز', 'Swift to judge': 'فیصلہ کرنے میں تیز', 'Swift to leave': 'جانے میں تیز'}},
    'Which are good habits on a hospital visit? Choose all that apply.': {
        'text': 'ہسپتال کی ملاقات میں کون سی عادتیں اچھی ہیں؟ تمام درست جوابات منتخب کریں۔', 'explanation': 'مختصر، باادب اور صاف ستھری۔',
        'options': {'Ask before praying': 'دعا سے پہلے اجازت لیں', 'Stay for several hours': 'کئی گھنٹے ٹھہریں',
                    'Respect privacy': 'رازداری کا احترام کریں', 'Wash your hands': 'ہاتھ دھوئیں'}},
    '"I was sick, and ye ___ me." (Matthew 25:36)': {
        'text': '"مَیں بیمار تھا اور تم نے میری ___ کی۔" (متی 25:36)', 'accepted': 'دیکھ بھال', 'explanation': 'متی 25:36۔'},
    'Match each psalm to its theme.': {
        'text': 'ہر زبور کو اُس کے موضوع سے ملائیں۔', 'explanation': 'مختلف ضرورتوں کے لئے زبور۔',
        'options': {'Psalm 23': ('زبور 23', 'رب میرا چرواہا ہے'), 'Psalm 121': ('زبور 121', 'میری مدد رب کی طرف سے ہے'),
                    'Psalm 51': ('زبور 51', 'توبہ کی دعا')}},
    'Put the steps of a short visit in order.': {
        'text': 'ایک مختصر ملاقات کے مراحل ترتیب سے لگائیں۔', 'explanation': 'پہلے سنیں، پھر کلام، پھر دعا۔',
        'options': {'Greet and listen': 'سلام کریں اور سنیں', 'Read a short psalm': 'کوئی مختصر زبور پڑھیں',
                    'Ask to pray, then pray': 'دعا کی اجازت لیں، پھر دعا کریں', 'Leave a word of hope': 'اُمید کی بات کہہ کر رخصت ہوں'}},
}

# The shorter Homiletics quiz words this question a little differently.
QUESTIONS["Which belong in a sermon's introduction? Choose all that apply."] = dict(
    QUESTIONS["Which of these belong in a sermon's introduction? Choose all that apply."],
    text='وعظ کی تمہید میں کون سی باتیں آتی ہیں؟ تمام درست جوابات منتخب کریں۔',
    explanation='مرکزی نکات وعظ کے درمیان میں آتے ہیں۔')

# Questions that pause a video.
VIDEO_QUESTIONS = {
    'How many human authors wrote the Bible?': {
        'text': 'بائبل کتنے انسانی مصنفین نے لکھی؟',
        'explanation': 'تقریباً 40 مختلف لوگوں نے 66 کتابیں لکھیں، جن میں بادشاہ، نبی، چرواہے، مچھیرے اور عالم شامل تھے۔',
        'options': {'About 20': 'تقریباً 20', 'About 30': 'تقریباً 30', 'About 40': 'تقریباً 40', '20': '20', '30': '30', '40': '40'}},
    'Which verse says "All Scripture is given by inspiration of God"?': {
        'text': 'کون سی آیت کہتی ہے: "ہر پاک نوشتہ اللہ کے روح سے وجود میں آیا ہے"؟',
        'explanation': '۲-تیمُتھیُس 3:16: "کیونکہ ہر پاک نوشتہ اللہ کے روح سے وجود میں آیا ہے اور تعلیم دینے… کے لئے مفید ہے۔"',
        'options': {'John 3:16': 'یوحنا 3:16', '2 Timothy 3:16': '۲-تیمُتھیُس 3:16', 'Romans 8:28': 'رومیوں 8:28', 'Psalm 23:1': 'زبور 23:1'}},
    'So, who wrote the Bible?': {
        'text': 'تو پھر، بائبل کس نے لکھی؟',
        'explanation': 'اللہ نے پیغام دیا؛ انسانی لکھنے والوں نے اُسے اپنے الفاظ میں لکھا۔',
        'options': {'Only God, with no human writers': 'صرف اللہ نے، کسی انسانی لکھنے والے کے بغیر', 'Only men, without God': 'صرف انسانوں نے، اللہ کے بغیر',
                    'God, through human writers': 'اللہ نے، انسانی لکھنے والوں کے ذریعے', 'Nobody knows': 'کوئی نہیں جانتا'}},
    'Over about how many years was the Bible written?': {
        'text': 'بائبل تقریباً کتنے سالوں میں لکھی گئی؟',
        'explanation': 'موسیٰ (تقریباً 1400 قبل مسیح) سے یوحنا (تقریباً 90 عیسوی) تک، تقریباً 1,500 سال۔',
        'options': {'About 100 years': 'تقریباً 100 سال', 'About 500 years': 'تقریباً 500 سال', 'About 1,500 years': 'تقریباً 1,500 سال', 'About 3,000 years': 'تقریباً 3,000 سال'}},
    'In which languages was the Bible first written?': {
        'text': 'بائبل سب سے پہلے کن زبانوں میں لکھی گئی؟',
        'explanation': 'عہدِ عتیق زیادہ تر عبرانی میں، کچھ ارامی میں؛ عہدِ جدید یونانی میں۔',
        'options': {'Latin and English': 'لاطینی اور انگریزی', 'Hebrew, Aramaic and Greek': 'عبرانی، ارامی اور یونانی', 'Greek only': 'صرف یونانی', 'Hebrew only': 'صرف عبرانی'}},
    'According to 2 Peter 1:21, how did the prophets speak?': {
        'text': '۲-پطرس 1:21 کے مطابق نبیوں نے کیسے کلام کیا؟',
        'explanation': '"پیش گوئی کرتے وقت انسانوں نے روح القدس سے تحریک پا کر اللہ کی طرف سے بات کی۔" (۲-پطرس 1:21)',
        'options': {'By their own will': 'اپنی مرضی سے', 'As they were moved by the Holy Spirit': 'روح القدس سے تحریک پا کر',
                    'From other ancient books': 'دوسری قدیم کتابوں سے', 'By a vote of the elders': 'بزرگوں کے ووٹ سے'}},
    'How many books are in the Bible?': {
        'text': 'بائبل میں کتنی کتابیں ہیں؟', 'explanation': '66 کتابیں: عہدِ عتیق میں 39 اور عہدِ جدید میں 27۔',
        'options': {'39': '39', '27': '27', '66': '66', '73': '73'}},
    'Who spoke to Moses from the burning bush?': {'text': 'جلتی جھاڑی میں سے موسیٰ سے کس نے کلام کیا؟',
        'options': {'God': 'اللہ', 'Aaron': 'ہارون'}},
}
# The user's own question on "Who Really Wrote the Bible - God or Man?".
VIDEO_QUESTIONS['How many human authors wrote the bible'] = VIDEO_QUESTIONS['How many human authors wrote the Bible?']

VERSES = {
    '2 Timothy 3:16': ('۲-تیمُتھیُس 3:16', 'کیونکہ ہر پاک نوشتہ اللہ کے روح سے وجود میں آیا ہے اور تعلیم دینے، ملامت کرنے، اصلاح کرنے اور راست باز زندگی گزارنے کی تربیت دینے کے لئے مفید ہے۔'),
    '2 Peter 1:21': ('۲-پطرس 1:21', 'کیونکہ کوئی بھی پیش گوئی کبھی بھی انسان کی تحریک سے وجود میں نہیں آئی بلکہ پیش گوئی کرتے وقت انسانوں نے روح القدس سے تحریک پا کر اللہ کی طرف سے بات کی۔'),
    'Psalm 119:105': ('زبور 119:105', 'تیرا کلام میرے پاؤں کے لئے چراغ ہے جو میری راہ کو روشن کرتا ہے۔'),
    'Isaiah 40:8': ('یسعیاہ 40:8', 'گھاس تو مُرجھا جاتی اور پھول گر جاتا ہے، لیکن ہمارے خدا کا کلام ابد تک قائم رہتا ہے۔'),
    'John 17:17': ('یوحنا 17:17', 'اُنہیں سچائی کے وسیلے سے مخصوص و مُقدّس کر۔ تیرا کلام ہی سچائی ہے۔'),
    'Hebrews 4:12': ('عبرانیوں 4:12', 'کیونکہ اللہ کا کلام زندہ، موثر اور ہر دو دھاری تلوار سے زیادہ تیز ہے۔'),
    'John 3:16': ('یوحنا 3:16', 'کیونکہ اللہ نے دنیا سے اِتنی محبت رکھی کہ اُس نے اپنے اکلوتے فرزند کو بخش دیا، تاکہ جو بھی اُس پر ایمان لائے ہلاک نہ ہو بلکہ ابدی زندگی پائے۔'),
    'Romans 3:23': ('رومیوں 3:23', 'سب نے گناہ کیا، سب اللہ کے اُس جلال سے محروم ہیں جس کا وہ تقاضا کرتا ہے،'),
    'Romans 6:23': ('رومیوں 6:23', 'کیونکہ گناہ کا اجر موت ہے جبکہ اللہ ہمارے خداوند مسیح عیسیٰ کے وسیلے سے ہمیں ابدی زندگی کی مفت نعمت عطا کرتا ہے۔'),
    'Ephesians 2:8': ('اِفسِیوں 2:8', 'کیونکہ یہ اُس کا فضل ہی ہے کہ آپ کو ایمان لانے پر نجات ملی ہے۔ یہ آپ کی طرف سے نہیں ہے بلکہ اللہ کی بخشش ہے۔'),
    'Acts 1:8': ('اعمال 1:8', 'لیکن تمہیں روح القدس کی قوت ملے گی جو تم پر نازل ہو گا۔ پھر تم یروشلم، پورے یہودیہ اور سامریہ بلکہ دنیا کی انتہا تک میرے گواہ ہو گے۔'),
    'Psalm 23:1': ('زبور 23:1', 'رب میرا چرواہا ہے، مجھے کمی نہ ہو گی۔'),
    'Psalm 46:1': ('زبور 46:1', 'اللہ ہماری پناہ گاہ اور قوت ہے۔ مصیبت کے وقت وہ ہمارا مضبوط سہارا ثابت ہوا ہے۔'),
    'Matthew 11:28': ('متی 11:28', 'اے تھکے ماندے اور بوجھ تلے دبے ہوئے لوگو، سب میرے پاس آؤ! مَیں تم کو آرام دوں گا۔'),
    '2 Corinthians 1:4': ('۲-کُرِنتِھیوں 1:4', 'جب بھی ہم مصیبت میں پھنس جاتے ہیں تو وہ ہمیں تسلی دیتا ہے تاکہ ہم اَوروں کو بھی تسلی دے سکیں۔'),
    'Isaiah 41:10': ('یسعیاہ 41:10', 'چنانچہ مت ڈر، کیونکہ مَیں تیرے ساتھ ہوں۔ دہشت مت کھا، کیونکہ مَیں تیرا خدا ہوں۔'),
}

DECKS = {
    'Who Wrote the Bible? Key Verses & Facts': ('بائبل کس نے لکھی؟ اہم آیات اور حقائق', 'اللہ نے ہمیں بائبل کیسے دی، اِس بارے میں اہم آیات، اور یاد رکھنے کے چند حقائق۔'),
    'Preaching Key Terms': ('منادی کی اہم اصطلاحات', 'وہ الفاظ جو ہر مُناد کو معلوم ہونے چاہئیں۔'),
    'Books of the Pentateuch': ('توریت کی کتابیں', None),
    'New Testament Key Verses': ('عہدِ جدید کی اہم آیات', None),
    'Theology Terms': ('الہیات کی اصطلاحات', None),
    'Key Dates in Church History': ('کلیسیا کی تاریخ کی اہم تاریخیں', None),
    'Verses of Comfort': ('تسلی کی آیات', None),
}
# Cards by English front: (Urdu front, Urdu back). Verse cards quote the Urdu Bible.
CARDS = {ref: VERSES[ref] for ref in VERSES}
CARDS.update({
    'How many books are in the Bible?': ('بائبل میں کتنی کتابیں ہیں؟', '66: عہدِ عتیق میں 39 اور عہدِ جدید میں 27۔'),
    'About how many people wrote the Bible?': ('بائبل تقریباً کتنے لوگوں نے لکھی؟', 'تقریباً 40، جن میں بادشاہ، نبی، چرواہے، مچھیرے اور ایک طبیب (لوقا) شامل تھے۔'),
    'Over about how many years was the Bible written?': ('بائبل تقریباً کتنے سالوں میں لکھی گئی؟', 'تقریباً 1,500 سال میں، موسیٰ سے یوحنا رسول تک۔'),
    'In which languages was the Bible first written?': ('بائبل سب سے پہلے کن زبانوں میں لکھی گئی؟', 'عبرانی، ارامی اور یونانی۔'),
    'Who is traditionally said to have written the first five books?': ('روایت کے مطابق پہلی پانچ کتابیں کس نے لکھیں؟', 'موسیٰ نے (پیدایش، خروج، احبار، گنتی، استثنا)۔'),
    'Homiletics': ('وعظ گوئی', 'وعظ تیار کرنے اور پیش کرنے کا فن اور علم۔'),
    'Hermeneutics': ('علمِ تفسیر', 'پاک کلام کی تشریح کے اصول اور طریقے۔'),
    'Exegesis': ('تشریح', 'سیاق و سباق میں متن سے اُس کا مطلب نکالنا۔'),
    'Eisegesis': ('غلط تشریح', 'اپنے خیالات متن میں ڈالنا۔ اِس سے بچنا چاہئے۔'),
    'Expository sermon': ('تفسیری وعظ', 'ایسا وعظ جس کے مرکزی نکات پاک کلام کے کسی حوالے کی وضاحت سے نکلتے ہیں۔'),
    'Topical sermon': ('موضوعاتی وعظ', 'کسی موضوع پر مبنی وعظ، جس میں کئی حوالے استعمال ہوں۔'),
    'Textual sermon': ('متنی وعظ', 'کسی مختصر متن پر وعظ جس کے حصے اُسی متن سے نکلتے ہیں۔'),
    'Big idea': ('مرکزی خیال', 'وہ ایک مرکزی سچائی جسے پہنچانے کے لئے وعظ بنایا جاتا ہے۔'),
    'Illustration': ('مثال', 'کوئی کہانی، تصویر یا نمونہ جو کسی سچائی کو واضح کرے۔'),
    'Application': ('عملی اطلاق', 'یہ دکھانا کہ سچائی کو آج ایمان اور زندگی کو کیسے بدلنا چاہئے۔'),
    'Kerygma': ('کیرگما', 'یونانی لفظ بمعنی "منادی": خوش خبری کا پیغام جس کی منادی کی جاتی ہے۔'),
    'Genesis': ('پیدایش', 'ابتدا: تخلیق، انسان کا گرنا، طوفان اور آبائے قوم۔'),
    'Exodus': ('خروج', 'بنی اسرائیل کی مصر سے رِہائی؛ کوہِ سینا پر شریعت۔'),
    'Leviticus': ('احبار', 'عبادت، قربانی اور پاک زندگی کے احکام۔'),
    'Numbers': ('گنتی', 'بیابان میں چالیس سال۔'),
    'Deuteronomy': ('استثنا', 'عہد کی تجدید کرنے والے موسیٰ کے الوداعی خطبے۔'),
    'Revelation': ('مکاشفہ', 'اللہ کا اپنے آپ کو ظاہر کرنا، تخلیق میں اور پاک کلام میں۔'),
    'Trinity': ('تثلیث', 'ایک خدا تین اقانیم میں: باپ، فرزند اور روح القدس۔'),
    'Incarnation': ('تجسم', 'خدا کے فرزند کا پورا انسان بننا جبکہ وہ پورا خدا بھی رہا۔'),
    'Justification': ('راست بازی', 'اللہ کا گناہ گار کو مسیح پر ایمان کے ذریعے راست باز قرار دینا۔'),
    'Sanctification': ('تقدیس', 'روح القدس کا عمر بھر کا کام جو ایمان دار کو پاک بناتا ہے۔'),
    'Atonement': ('کفارہ', 'صلیب پر مسیح کا کام جو گناہ گاروں کو اللہ سے ملاتا ہے۔'),
    'AD 30': ('تقریباً سنہ 30', 'پنتکست: کلیسیا پر روح القدس کا نزول (اعمال 2)۔'),
    'AD 313': ('سنہ 313', 'فرمانِ میلان: مسیحیوں کے لئے عبادت کی آزادی۔'),
    'AD 325': ('سنہ 325', 'نیقیہ کی کونسل اور نیقیہ کا عقیدہ۔'),
    '1517': ('1517', 'لوتھر کے پچانوے نکات سے اصلاحِ کلیسیا کا آغاز۔'),
    '1611': ('1611', 'بائبل کا کنگ جیمز ترجمہ شائع ہوا۔'),
})

ASSIGNMENTS = {
    'Essay: The Exodus Narrative': ('مضمون: خروج کا بیان', 'خروج کے الہیاتی مطلب پر 1,500 الفاظ کا مضمون لکھیں۔'),
    'Reflection: Covenant in Genesis': ('غور و فکر: پیدایش میں عہد', 'ایک صفحے پر لکھیں کہ ابراہیم کے ساتھ عہد باقی پیدایش کو کیسے شکل دیتا ہے۔'),
    'Book review: The Prophets': ('کتاب پر تبصرہ: انبیا', 'عہدِ عتیق کے انبیا پر اپنی پسند کی کسی کتاب پر تبصرہ کریں۔'),
    'Exegesis: Romans 8': ('تشریح: رومیوں 8', 'رومیوں 8:1-17 کا آیت بہ آیت مطالعہ کریں۔'),
}

# ── Writing it ───────────────────────────────────────────────────────
done = {}


def by_english(model, field):
    records = env[model].with_context(lang='en_US', active_test=False).search([])
    index = {}
    for record in records:
        index.setdefault(norm(record[field]), []).append(record)
    return index


def put(record, vals):
    record.with_context(lang=UR).write({k: v for k, v in vals.items() if v})
    done[record._name] = done.get(record._name, 0) + 1


def simple(model, table, field='name', second=None):
    index = by_english(model, field)
    for english, urdu in table.items():
        for record in index.get(norm(english), []):
            if isinstance(urdu, tuple):
                vals = {field: urdu[0]}
                if second and urdu[1]:
                    vals[second] = urdu[1]
                put(record, vals)
            else:
                put(record, {field: urdu})


simple('college.program', PROGRAMS)
simple('college.term', TERMS)
simple('college.course', COURSES)
simple('college.course.module', MODULES)
simple('college.quiz', QUIZZES, second='description')
simple('college.flashcard.deck', DECKS, second='description')
simple('college.assignment', ASSIGNMENTS, second='description')

# Lessons: names, plus readings and the "Quiz: ..." / "Flashcards: ..." names.
lesson_index = by_english('college.course.content', 'name')
for english, (urdu_name, urdu_body) in LESSONS.items():
    for lesson in lesson_index.get(norm(english), []):
        put(lesson, {'name': urdu_name, 'body': urdu_body if lesson.content_type == 'text' else None})
for key, lessons in lesson_index.items():
    for lesson in lessons:
        for prefix, urdu_prefix, table in (('quiz: ', 'کوئز: ', QUIZZES), ('flashcards: ', 'یادداشتی کارڈ: ', DECKS)):
            if key.startswith(prefix):
                rest = {norm(k): v[0] for k, v in table.items()}.get(key[len(prefix):])
                if rest:
                    put(lesson, {'name': urdu_prefix + rest.replace('کوئز: ', '')})


def translate_questions(model, option_model, table):
    index = by_english(model, 'text')
    for english, spec in table.items():
        for question in index.get(norm(english), []):
            put(question, {'text': spec['text'], 'explanation': spec.get('explanation'),
                           'accepted_answers': spec.get('accepted') if 'accepted_answers' in question._fields else None})
            options = spec.get('options') or {}
            by_text = {norm(k): v for k, v in options.items()}
            for option in question.option_ids.with_context(lang='en_US'):
                urdu = by_text.get(norm(option.text))
                if urdu is None:
                    continue
                if isinstance(urdu, tuple):
                    put(option, {'text': urdu[0], 'match_text': urdu[1]})
                else:
                    put(option, {'text': urdu})


translate_questions('college.quiz.question', 'college.quiz.option', QUESTIONS)
translate_questions('college.video.question', 'college.video.question.option', VIDEO_QUESTIONS)

card_index = by_english('college.flashcard', 'front')
for english, (front, back) in CARDS.items():
    for card in card_index.get(norm(english), []):
        put(card, {'front': front, 'back': back})

env.cr.commit()
print('Urdu written: ' + ', '.join('%s %d' % (model.split('.', 1)[1], count) for model, count in sorted(done.items())))
