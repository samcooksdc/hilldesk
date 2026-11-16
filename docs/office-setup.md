# Office setup

This guide covers what an office configures on day one, after the
deployment is running ([deployment.md](deployment.md)) and Graph is
connected ([graph-setup.md](graph-setup.md)).

## 1. Create the office and its first admin

Sign in once through SSO so your HillDesk account exists. Then run this from
a one-off task with the production settings:

```bash
python manage.py shell -c "
from apps.authentication.models import Office, User
office, _ = Office.objects.get_or_create(name='Office of Rep. Example')
roles = office.create_default_roles()          # admin, scheduler, staff
u = User.objects.get(email='you@your-office.example.com')
u.office = office
u.assign_role(roles['admin'])
u.save()
"
```

From then on, admins manage everything else in the app's **Settings** pages.

## 2. Settings, in order

| Area | What to set |
| --- | --- |
| Office profile | Member name, district, district office address. These feed email templates and exports. |
| Staff and roles | Assign each staffer (after their first sign-in) a role: **admin** (everything, including settings), **scheduler** (runs the inbox and approvals) or **staff** (sees and reviews their assigned items). Set each staffer's legislative areas so requests route to the right people. |
| Event choices | Statuses, types and formats your office uses |
| Approval routing | Who must sign off on which kinds of requests, and in what order |
| Email templates | Reply templates for accept, decline, request-for-info and others. Load starters with `python manage.py create_email_templates`. |
| Export templates | The `.docx` daily and weekly briefing and event-detail layouts. Load the built-ins with `python manage.py generate_export_templates`, then edit them to your house style. |

## 3. Ingestion

1. Make sure `SCHEDULING_MAILBOXES` and `INTERNAL_EMAIL_DOMAINS` are set.
2. Seed the sender allowlist:
   `python manage.py seed_sender_reputation`
3. Watch the first sweep. New mail shows up as draft events in **Inbox**,
   escalations in **Triage**, and filtered mail in **Diverted mail**.
   Nothing reaches the calendar until someone approves it.
4. Spend the first week reviewing **Diverted mail** and promoting anything
   the funnel got wrong. Promotions feed the sender-reputation scores.

## 4. Optional

- House floor schedule on the dashboard: Celery beat refreshes it; run
  `python manage.py fetch_house_floor_schedule` once to fill it immediately.
- Calendar sync: on by default (`ENABLE_CALENDAR_SYNC`). Approved events are
  written to the creating staffer's Outlook calendar.

## Try it first

You can rehearse all of this locally, with fictional data and no cloud
account: `python manage.py bootstrap_demo`, then sign in as `samuel` /
`demo`.
