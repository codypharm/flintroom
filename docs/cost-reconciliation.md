# Reconciling what a room costs

**#14, and Open Risk #4.** Every price in `Product.md` §4.4–4.5 rests on an
unverified $0.12/min interrogation assumption, and `CLAUDE.md` forbids shipping
or changing a price without observed cost behind it. `app/modules/voice/rates.py`
says the same thing in its own header: the rates it carries are published, not
observed, and "#14 is what replaces this with an invoice."

This is the procedure for doing that. It is deliberately a document rather than
a script: the vendor half cannot be automated from inside the repo, and a
half-automated reconciliation is one somebody trusts without having done.

---

## What the closed test makes possible

Until there was real usage there was nothing to reconcile. A tester window is
the first time three separate questions can be answered from data rather than
from assumption, and only one of them needs an invoice:

1. **Does our computed cost match the vendors' bills?** Needs invoices.
2. **What does a room actually cost per interrogation minute?** Ours alone.
3. **How long is a debrief, really?** Ours alone — and it is the question
   `CLAUDE.md` explicitly parks until there is an observed median.

Do 2 and 3 first. They cost nothing and they are useful whatever the invoices
say.

---

## Our side

Run in the Supabase SQL editor. All of these read `session_costs`, which is
written on the settle path — a room that never settled is not in here, and
that is correct: it did not cost a full room either.

### Usage over a window

```sql
select
  count(*)                              as rooms,
  sum(interrogation_seconds) / 60.0     as interrogation_minutes,
  sum(tts_characters_synthesized)       as tts_characters,
  sum(stt_seconds_processed)            as stt_seconds,
  sum(llm_input_tokens)                 as llm_input_tokens,
  sum(llm_output_tokens)                as llm_output_tokens,
  sum(computed_cost_usd)                as our_cost_usd
from session_costs
where recorded_at >= '2026-08-01' and recorded_at < '2026-09-01';
```

Use calendar month boundaries, and the same ones the invoice uses. A window
that disagrees with the bill by three days is a reconciliation that will never
close and will look like a rate error.

### Cost per interrogation minute — the number §4.4 rests on

```sql
select
  sum(computed_cost_usd) / nullif(sum(interrogation_seconds) / 60.0, 0)
    as usd_per_interrogation_minute
from session_costs
where recorded_at >= '2026-08-01' and recorded_at < '2026-09-01';
```

`docs/voice-cost.md` measured ~$0.042/min average and $0.067/min for the
chattiest room. §4.4 budgets ~$0.16/min all-in. **A figure inside that band is
not a result — it is the same estimate arriving twice**, because
`computed_cost_usd` is calculated from the very rates `voice-cost.md` derived.
Only the invoice comparison below can move it.

### How long a debrief actually runs

```sql
select
  percentile_cont(0.5) within group (order by debrief_seconds) / 60.0  as median_debrief_minutes,
  percentile_cont(0.9) within group (order by debrief_seconds) / 60.0  as p90_debrief_minutes,
  percentile_cont(0.5) within group (order by sparring_seconds) / 60.0 as median_sparring_minutes,
  max(debrief_seconds + sparring_seconds) / 60.0                       as longest_unmetered_minutes
from session_costs
where recorded_at >= '2026-08-01'
  and (debrief_seconds > 0 or sparring_seconds > 0);
```

**This one is worth running on its own.** `CLAUDE.md` holds a ~20 minute soft
cap on unmetered coaching and says plainly that its original reason — a cost
circuit breaker against an idle open session — was removed when coaching became
turn-based, and that what it protects now is the promise rather than the bill.
It then parks the number: §4.3 "wants the observed median before the 20 is
defended". This query is that median. If p90 is comfortably under 20 the cap is
generous and stays; if the median is near it, the cap is doing real work and the
copy around it needs to change.

### Where the money goes, by line

```sql
select
  round(100 * sum(tts_characters_synthesized) * 0.04 / 371
        / nullif(sum(computed_cost_usd), 0), 1) as tts_share_pct,
  round(100 * sum(stt_seconds_processed) * 0.39 / 3600
        / nullif(sum(computed_cost_usd), 0), 1) as stt_share_pct
from session_costs
where recorded_at >= '2026-08-01' and recorded_at < '2026-09-01';
```

The literals mirror `rates.py`. If TTS is not around 88% of the bill, either the
mix has changed or the adapter has stopped reporting one of the lines — both
worth knowing before comparing anything to an invoice.

---

## Their side

Pull each for **the same window**, to the day.

| Vendor | Where | What to read |
| --- | --- | --- |
| ElevenLabs | Usage page, and the invoice | Characters synthesised, and the dollar total. Credits are not characters — Flash v2.5 bills 0.5 credits per character, so a credit figure halves before it compares. |
| ElevenLabs (Scribe) | Same invoice, separate line | Seconds or hours transcribed. |
| Model provider | Billing / usage export | Input and output tokens, and the dollar total. |

Two things that will not appear in `session_costs` and must be subtracted
before comparing, or the invoice will look mysteriously high:

- **Ingestion.** Document extraction runs on its own model budget and is not a
  room. `EXTRACTION_PROVIDER` is the path.
- **Anything you ran by hand.** Test calls, the `/tmp/tts.sh` reproduction from
  the 2026-08-31 outage, console experiments. These land on the invoice and
  never touch a settle path.

---

## The comparison, and what it decides

Set them side by side per vendor:

```
ours   = sum(computed_cost_usd), split by line
theirs = invoice total, minus ingestion, minus manual usage
```

§4.3's acceptance criterion, repeated in `CLAUDE.md`: **within 10%.**

**Inside 10%.** The rates in `rates.py` hold. Record the observed
`usd_per_interrogation_minute` in `docs/voice-cost.md` with the window it came
from, and §4.4's margins are backed by something for the first time.

**Ours is low.** The likeliest cause is the TTS rate, because synthesis is ~88%
of a room and `TTS_USD_PER_CHARACTER` is the one number in `rates.py` that was
*derived* rather than read off a contract — it comes from $0.04 per
interrogation minute over 371 characters/minute, which is an inference about the
product, not a term of the deal. Correct the constant, and the daily spend
ceiling starts protecting the amount it was supposed to.

**Ours is high.** Usually a tier discount the published rate does not know
about. Pleasant, and still a code change: an over-estimate makes the circuit
breaker trip early and every margin look worse than it is.

**Either way, `rates.py` changes in a commit with a diff**, which is what its
header says the number deserves. Not a setting, not an environment variable —
two deployments disagreeing about what a room cost would make the whole table
incomparable.

---

## What this does not settle

`provider_reported_cost` exists on the row for a per-session comparison and is
null everywhere, because no adapter fills it. Filling it would make this a
continuous check rather than a quarterly one. That is worth doing and it is not
this task: the reconciliation has to be done by hand once before it is worth
automating, or the automation inherits an assumption nobody has tested.
