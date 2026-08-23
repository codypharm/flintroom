# Analytics — first-party, in our own Postgres

Resolved with the architect on 2026-08-24 (task #105): first-party events
over Aptabase or PostHog. No SDK on the phone, no new data processor in the
privacy policy, no bill — the events land in the same Supabase Postgres as
everything else, behind the same deny-all RLS, reachable only through
FastAPI. Read this before adding an event, a property, or any analytics
dependency.

## What an event is, and is not

**A name, a user, and the server's clock.** `app_events(id, user_id, name,
at)` — and deliberately no properties column. A JSON blob on an analytics
row is where transcript text would eventually leak into a table with a
twelve-month lifetime, and the pattern on the event name
(`^[a-z][a-z0-9_.]{0,63}$`, enforced at the endpoint) is the whole defence
against the table holding prose. A property earns a column, a migration and
a privacy-policy sentence when a question needs it — not before.

**The funnel is not here, on purpose.** Rooms started, debriefs opened,
sparring used, minutes bought — every one of those is a row in the domain
table that owns the act, written at the moment it happened, with better
fidelity than any client event could carry. Duplicating them here would be a
second copy free to disagree. What the domain tables cannot answer is
whether a person *opened the app at all* — the retention question, Open Risk
#1's other half — so the one instrumented event in v1 is **`app_open`**,
fired once per signed-in cold start.

The endpoint accepts any name-shaped event, so client instrumentation can
grow without a server deploy. Growing it is a decision, not a habit: every
new name is a sentence in the privacy policy's events disclosure.

## The lifecycle

- **Written** by `POST /v1/events` — authenticated, rate-limited, the user
  taken from the credential and never the body, the time stamped by the
  server because phone clocks lie. 202 and an empty body: telemetry is never
  something a screen waits on, and the client (`app/src/lib/analytics`)
  fires and forgets accordingly — no failure reaches a screen, and a launch
  in a tunnel simply goes uncounted.
- **Forgotten at twelve months** by a sweep riding the same loop as every
  other retention promise. The number is disclosed in
  `docs/privacy-policy.md`; moving it moves the disclosure.
- **Destroyed with the account.** `app_events` is in the deletion purge's
  `PURGED` list — behavioral data has no life beyond its person, and the
  completeness tests in `test_account_deletion.py` refuse any
  `user_id`-carrying table without a deletion decision.

## Where to look at it

The Supabase dashboard → **SQL Editor**, against the same database the app
runs on. No new tool, no new account. The queries worth saving there:

**Daily active users, last 30 days**

```sql
select date_trunc('day', at) as day, count(distinct user_id) as people
from app_events
where name = 'app_open' and at > now() - interval '30 days'
group by 1 order by 1;
```

**Do they come back? — week-over-week return**

```sql
with weeks as (
  select user_id, date_trunc('week', at) as week
  from app_events where name = 'app_open' group by 1, 2
)
select this.week,
       count(distinct this.user_id) as active,
       count(distinct back.user_id) as returned_next_week
from weeks this
left join weeks back
  on back.user_id = this.user_id
 and back.week = this.week + interval '1 week'
group by 1 order by 1;
```

**Did being grilled drive them off? — opens after a first room**

```sql
select count(distinct e.user_id) as came_back
from app_events e
join sessions s on s.user_id = e.user_id
where e.name = 'app_open'
  and e.at > s.settled_at + interval '1 day';
```

The funnel itself reads off the domain tables — `sessions` for rooms and
endings, `session_coach_turns` for debrief engagement, `ledger_entries` for
money — and joins to `app_events` only when a question spans both.

## Considered and declined

- **Aptabase / PostHog** — dashboards out of the box, at the price of a
  third-party SDK on a mic-permission app, a new processor in the privacy
  policy, and a bill. SQL against our own Postgres answers the v1 questions;
  a dashboard becomes worth revisiting when somebody who cannot write SQL
  needs to read these numbers.
- **A properties column** — see above. The refusal is the design.
- **Anonymous events** — the endpoint is authenticated, so a signed-out
  launch is uncounted. The wedge's questions are about people who have
  accounts; counting strangers is marketing's job and lives with the
  website, not the app backend.
