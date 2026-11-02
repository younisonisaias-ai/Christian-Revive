"""Removes exactly what sample_data.py created, and nothing else.

    docker compose exec -T service_revive_odoo19 odoo shell -d revive_db --no-http \
        < /path/to/revive_bible_college/scripts/remove_sample_data.py

If a real record now depends on a sample one (a real student enrolled in a
sample course, say), nothing is removed and the reason is printed.
"""
import json

PARAM = 'revive_bible_college.sample_data'
env = env(su=True)
Params = env['ir.config_parameter']
saved = Params.get_param(PARAM)

if not saved:
    print('There is no sample data to remove.')
else:
    created = json.loads(saved)
    try:
        with env.cr.savepoint():
            applicants = env['college.applicant'].browse(created.get('college.applicant', [])).exists()
            students = env['college.student'].browse(created.get('college.student', [])).exists()
            applicants.write({'student_id': False})
            students.write({'applicant_id': False})
            # Saved children first, so this order is safe.
            for model, ids in created.items():
                env[model].browse(ids).exists().unlink()
            Params.set_param(PARAM, False)
        env.cr.commit()
        print('Sample data removed.')
    except Exception as error:
        print('Nothing was removed, because: %s' % error)
