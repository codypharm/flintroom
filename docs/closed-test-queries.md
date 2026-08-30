# Watching the closed test

**Written 2026-08-30, for the fourteen days that decide production access.**

Twelve testers are about to use Flintroom, and without these the fortnight
produces impressions rather than knowledge — "some people tried it" instead of
"nine installed, seven opened a room, four reached the debrief, one came back".
Google also asks, in the production-access application, how the test went and
what changed because of it. These queries write those answers.

**No new events, and none needed.** `docs/analytics.md` deliberately keeps the
funnel in the domain tables: `app_events` carries only `app_open`, and
everything below is read from the rows the product already writes when it does
its job. A funnel built from purpose-built events would be a second version of
the truth, free to drift from the first.

Run them in the Supabase SQL editor. Set `FROM_DATE` to the day the first
tester installs, everywhere it appears.

---

## The funnel, in one query

Each row is a person; the columns are how far they got.

```sql
with people as (
  select user_id, min(created_at) as first_seen
  from auth_identities
  where created_at > 'FROM_DATE'
  group by user_id
)
select
  p.user_id,
  p.first_seen::date                                as joined,
  (select count(*) from situations s
     where s.user_id = p.user_id)                   as described_a_room,
  (select count(*) from sessions x
     where x.user_id = p.user_id)                   as rooms_started,
  (select count(*) from sessions x
     where x.user_id = p.user_id
       and x.state = 'settled')                     as rooms_finished,
  (select count(*) from session_coach_turns t
     join sessions x on x.id = t.session_id
    where x.user_id = p.user_id)                    as coach_turns,
  (select count(*) from session_sparring_attempts a
     join sessions x on x.id = a.session_id
    where x.user_id = p.user_id)                    as sparring_attempts,
  (select count(distinct e.at::date) from app_events e
     where e.user_id = p.user_id)                   as days_opened
from people p
order by p.first_seen;
```

**How to read it.** `rooms_started` at zero means they installed and never
faced the panel — the most important number in the table, and the one Open
Risk #1 is about. `rooms_finished` below `rooms_started` means rooms are
breaking or being abandoned; check `end_reason` below. `coach_turns` at zero
across the board would mean the debrief is not being discovered, which is a
navigation problem rather than a taste one. `days_opened` above one is the
only genuine retention signal in the set.

## Why rooms ended

```sql
select state, end_reason, count(*) as rooms
from sessions
where started_at > 'FROM_DATE'
group by state, end_reason
order by rooms desc;
```

`idle_timeout` is ordinary — somebody stopped talking. `provisioning_failed`
or a spike in anything provider-shaped is the signal that **credits or
concurrency ran out** (see `docs/voice-cost.md`); those rooms refund
automatically, but the tester saw a room that broke.

## What it is costing

```sql
select
  count(*) as rooms,
  round(sum(interrogation_seconds) / 60.0, 1) as minutes,
  sum(stt_seconds_processed)
    + round(sum(tts_characters_synthesized) * 0.5) as credits_low,
  sum(stt_seconds_processed)
    + sum(tts_characters_synthesized)              as credits_high
from session_costs
where recorded_at > 'FROM_DATE';
```

Bracketed rather than exact, because synthesis bills 0.5 credits per character
on Flash and 1.0 on v3 and rooms use a mix. **Upgrade the ElevenLabs plan when
`credits_high` leaves under ~5,000 of the balance**: when credits hit zero
every room fails at once, for everybody, and upgrading adds to the balance
rather than replacing it, so there is nothing to gain by cutting it fine.

## Whether the panel is doing its job

```sql
select chosen_by, count(*) as lines
from session_transcript_lines l
join sessions s on s.id = l.session_id
where s.started_at > 'FROM_DATE'
  and l.speaker <> 'user'
group by chosen_by
order by lines desc;
```

`finding` rows are the Auditor catching a contradiction — the wedge working.
`fallback` is keyword routing standing in for a late or failed model call;
a high share means the room is being assembled by the cheap path more often
than intended (watched since 2026-08-27, when it ran near 20%).

## Who is stuck where — the qualitative follow-up

```sql
select s.user_id, s.started_at, s.state, s.end_reason,
       count(l.id) filter (where l.speaker = 'user') as things_they_said
from sessions s
left join session_transcript_lines l on l.session_id = s.id
where s.started_at > 'FROM_DATE'
group by s.id
order by s.started_at desc;
```

A room with one or two user lines is somebody who opened it, heard the
opener, and stopped — worth asking that person what happened, because they
will not volunteer it.
