#!/usr/bin/env bash
# The five release gates of CLAUDE.md, run against the real dev stack.
#
# Not a unit suite: every flow drives the installed dev client on the attached
# Android device/emulator, against the running backend, the real database, and
# the real model/voice vendors. It costs real cents and real minutes — gate 2
# alone is ~3 minutes of metered room by design.
#
# Preconditions (the same ones docs/device-testing.md sets up):
#   docker compose up -d                      # Postgres + MinIO
#   uvicorn on 0.0.0.0:8000, npx expo start   # backend + Metro
#   dev client installed and SIGNED IN on the adb device
#   docs/testing-assets/kettleworks-deck.pdf  # pushed here automatically
#
# Gate 5 (Auditor → the right archetype interrupts) is deliberately absent:
# it requires real speech into a real microphone, which an emulator does not
# have. It is scripted for a human in docs/testing-assets/pitch-script.md.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$PATH:$HOME/.maestro/bin"

sql() { docker exec flintroom-db psql -U flintroom -d flintroom_dev -tAc "$1"; }

say() { printf '\n== %s ==\n' "$1"; }

say "preconditions"
command -v maestro >/dev/null || { echo "maestro is not installed (https://get.maestro.mobile.dev)"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "no adb device"; exit 1; }
curl -sf -o /dev/null http://localhost:8000/v1/materials/limits -H "Authorization: Bearer x" || true
sql "SELECT 1" >/dev/null || { echo "dev database unreachable"; exit 1; }
adb push ../../docs/testing-assets/kettleworks-deck.pdf /sdcard/Download/ >/dev/null

say "gate 1: room within allowance"
maestro test flows/01-room-within-allowance.yaml

# The account driving the device is whoever gate 1's room belongs to — read,
# never hardcoded, so the suite follows whatever account the device holds.
USER=$(sql "SELECT user_id FROM sessions ORDER BY started_at DESC LIMIT 1")
[ -n "$USER" ] || { echo "gate 1 left no session to read the account from"; exit 1; }
echo "device account: ${USER%%-*}..."

# Settlement is asynchronous behind the End tap; give it a moment to land.
settled_as() {
  for _ in $(seq 1 30); do
    REASON=$(sql "SELECT coalesce(end_reason,'') FROM sessions WHERE user_id='$USER' ORDER BY started_at DESC LIMIT 1")
    [ -n "$REASON" ] && { echo "$REASON"; return; }
    sleep 2
  done
  echo "never-settled"
}
NEWEST=$(settled_as)
[ "$NEWEST" = "user_ended" ] || { echo "gate 1 room settled as '$NEWEST', wanted user_ended"; exit 1; }
echo "settle verified: user_ended"

say "gate 2: out of minutes mid-room (about 3 minutes, by design)"
# Dev-only: production balances change through LedgerService alone.
sql "UPDATE accounts SET balance_free_seconds=20, balance_allowance_seconds=0, balance_topup_seconds=0 WHERE user_id='$USER'" >/dev/null
maestro test flows/02-out-of-minutes.yaml
REASON=$(settled_as)
# On a silent emulator the 90s idle timeout always beats the grace cap
# (overdraft + 120s of grace is ~135s), so grace_cap itself is reachable only
# with a speaking presenter — the same physics that keeps gate 5 manual. What
# this run pins is the half automation can reach: the room ended by a
# server-side decision, never a hard cut, and the app arrived at the debrief
# without a tap. The grace ledger math is pinned by the backend meter tests;
# the spoken version of this gate is docs/device-testing.md §4.
case "$REASON" in
  grace_cap|idle_timeout) echo "settle verified: $REASON (server-decided, no hard cut)";;
  *) echo "gate 2 room settled as '$REASON', wanted a server-decided ending"; exit 1;;
esac
# A usable balance back, so nothing after runs against an empty account.
sql "UPDATE accounts SET balance_free_seconds=900 WHERE user_id='$USER'" >/dev/null

say "gate 3: debrief -> sparring -> prep sheet (seeded room)"
SID=$(python3 -c "import uuid; print(uuid.uuid4())")
sql "DELETE FROM session_transcript_lines WHERE session_id IN (SELECT id FROM sessions WHERE rehearsal_name='E2E seeded pitch')" >/dev/null
sql "DELETE FROM session_panelists WHERE session_id IN (SELECT id FROM sessions WHERE rehearsal_name='E2E seeded pitch')" >/dev/null
sql "DELETE FROM sessions WHERE rehearsal_name='E2E seeded pitch'" >/dev/null
sql "INSERT INTO sessions (id, user_id, state, started_at, settled_at, end_reason, last_progress_at, rehearsal_name)
     VALUES ('$SID', '$USER', 'settled', now() - interval '10 minutes', now() - interval '2 minutes', 'user_ended', now(), 'E2E seeded pitch')" >/dev/null
sql "INSERT INTO session_panelists (session_id, name, seat) VALUES ('$SID','cfo',0), ('$SID','technical_skeptic',1), ('$SID','champion',2)" >/dev/null
sql "INSERT INTO session_transcript_lines (session_id, ordinal, speaker, text) VALUES
  ('$SID', 0, 'user', 'Kettleworks sells preventive maintenance subscriptions for commercial coffee equipment.'),
  ('$SID', 1, 'cfo', 'Your churn is four and a half percent a month. What does a replacement location cost you?'),
  ('$SID', 2, 'user', 'We are really pleased with the trajectory.'),
  ('$SID', 3, 'cfo', 'That is not a number. What is your customer acquisition cost?'),
  ('$SID', 4, 'user', 'It is nine hundred and forty dollars, and payback is fourteen months.'),
  ('$SID', 5, 'technical_skeptic', 'Seven technicians cover two hundred and ten locations. What breaks first at six hundred?'),
  ('$SID', 6, 'user', 'We are looking at expansion.'),
  ('$SID', 7, 'champion', 'Give me the one sentence you want this room to remember.')" >/dev/null
echo "seeded session ${SID%%-*}..."
maestro test flows/03-debrief-sparring-prep.yaml

say "gate 4: the buy screen (purchases blocked on #96 — render half only)"
maestro test flows/04-buy-screen.yaml

say "all runnable gates passed"
