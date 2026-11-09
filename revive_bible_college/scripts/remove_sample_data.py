"""Removes exactly what sample_data.py and lms_sample_data.py created, and
nothing else.

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db --no-http \
        < /path/to/revive_bible_college/scripts/remove_sample_data.py

Lessons that someone else added to a sample module are kept (they just no
longer have a module). If a real record depends on a sample one (a real
student enrolled in a sample course, say), nothing is removed and the reason
is printed.
"""
import json

PARAM = 'revive_bible_college.sample_data'
LMS_PARAM = 'revive_bible_college.sample_data_lms'
env = env(su=True)
Params = env['ir.config_parameter']
saved = Params.get_param(PARAM)
saved_lms = Params.get_param(LMS_PARAM)

if not saved and not saved_lms:
    print('There is no sample data to remove.')
else:
    try:
        with env.cr.savepoint():
            if saved_lms:
                lms = json.loads(saved_lms)
                modules = env['college.course.module'].browse(lms.get('college.course.module', [])).exists()
                ours = set(lms.get('college.course.content', []))
                # Keep lessons someone else filed under a sample module.
                env['college.course.content'].search([
                    ('module_id', 'in', modules.ids), ('id', 'not in', list(ours))]).write({'module_id': False})
                for model, ids in lms.items():  # saved children first
                    env[model].browse(ids).exists().unlink()
                Params.set_param(LMS_PARAM, False)
            if saved:
                created = json.loads(saved)
                applicants = env['college.applicant'].browse(created.get('college.applicant', [])).exists()
                students = env['college.student'].browse(created.get('college.student', [])).exists()
                applicants.write({'student_id': False})
                students.write({'applicant_id': False})
                for model, ids in created.items():  # saved children first
                    env[model].browse(ids).exists().unlink()
                Params.set_param(PARAM, False)
        env.cr.commit()
        print('Sample data removed.')
    except Exception as error:
        print('Nothing was removed, because: %s' % error)
