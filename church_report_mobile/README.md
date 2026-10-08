# Church Mobile Report Exports

Companion Odoo addon for Revive's Admin church PDF exporter. Requires the existing
`church_management`, `church_finance` and `church_give` modules (Odoo 19).
It adds two read-only RPC methods to `church.dashboard`; it does not change
employees, login credentials, membership records or permissions.

## Install on the app's Odoo server

1. Copy this **whole folder**, named `church_report_mobile`, into the configured
   custom addons directory on the server that serves the app's database. Installing
   on a different local Odoo instance will not update the app's server.
2. Restart the Odoo service so it discovers the new Python code.
3. Sign into Odoo as its system administrator. Enable developer mode, open Apps,
   and run **Update Apps List**. Remove the default Apps search filter if needed.
4. Search **Church Mobile Report Exports** and install it in the app's database
   (`revive_db` in the current deployment). Ensure all three dependencies are
   installed and current. Back up the database before installation.
5. Install/run the updated Revive app build. Login as the same working Admin;
   no new employee link or password setup is required.

For a deployment managed by CLI, stop Odoo workers first and use the deployment's
usual Odoo configuration and database account to run:

```text
odoo -c <server-odoo.conf> -d revive_db -i church_report_mobile --stop-after-init
```

For later code updates use `-u church_report_mobile` and restart workers. Do not
run two Odoo processes against the database during installation. Container names,
server paths and SSH access are deployment-specific and are not embedded here.

## Check in the app

Admin Portal → Church Dashboard & PDF Reports → Export full church report.

* Choose This month, This year, All time or Custom dates (both days included).
* Select Summary for totals, or Detailed for individual records.
* Select the sections needed. Private prayer details and pastoral notes default
  to off; they require Detailed, Prayer and pastoral care, and explicit opt-in.
* Generate PDF. Progress shows the section being loaded. Failed requests retry
  automatically up to three attempts. After exhausted retries, choose Retry failed
  sections or explicitly Preview incomplete report. Missing sections are marked
  on the PDF cover and every footer. Never treat an incomplete PDF as a full report.
* Use the existing PDF preview's print/save/share controls.

## Scope and limitations

Calendar dates use the linked Admin Odoo user's timezone, falling back to the
Odoo session user's timezone then UTC. Datetime filters cover local midnight
through, but not including, the midnight after the final date. Date fields include
both bounds. Donations include completed transactions only and use transaction
dates; attendance uses check-in time; services use start time; prayer uses creation
time; notes use note date; visitors use first visit; pledges use start date.
Member/family/group/assignment directories reflect current records, including
archived records. Pledge paid balances and prayer/member status are current.
This is not a historical balance reconstruction or a transactional database
snapshot: information can change during export or between retries.

Individual records are loaded in pages of 100 (server hard limit 200 per request),
using ID cursors with no overall record cap. The app runs at most three page
requests concurrently. PDFs still use device memory and have a 500-page safety
limit; choose Summary or fewer sections for exceptionally large directories.
Successful sections are reused on a manual retry if their counts have not changed.

Both RPC methods enforce an enabled `staff_role == 'admin'` employee and follow
the existing church app's requester staff identity contract. Staff roles cannot
use these exports. As with the existing church API, requester identity is supplied
by the app's authenticated session through its configured Odoo connection.
The deployment must keep that integration connection restricted. Private prayer
and note page requests are denied unless explicitly included; member care status
is also removed from ordinary detailed responses.

## Validation

Local date/rule and model-contract tests (without an Odoo runtime):

```text
python -m unittest discover -s backend/church_report_mobile -p "test_*.py"
```

Requires `pytz`, which is included in Odoo's normal environment. Before production
use, verify in a staging Odoo 19 database with synthetic records: period start/end
transactions, more than 100 members, an ordinary Staff account, a disabled Admin,
private opt-in/off, and a temporary connection failure. Local tests mock the ORM;
they do not substitute for an installed-server test.
