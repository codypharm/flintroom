"""Bring the ElevenLabs agent in line with what the adapter requires.

    uv run python -m scripts.configure_agent            # show current state
    uv run python -m scripts.configure_agent --apply    # write the changes

Exists because these settings are scattered across the dashboard and several of
them are not exposed there at all, while getting any of them wrong fails in a
way that is hard to read: an audio format mismatch arrives as noise, and a
conversation cap below our own arrives as every session refunding itself.

Only the settings the adapter depends on are touched. The prompt, first message
and voice are left exactly as they are — those are the panel's character, which
is a product decision and not this script's business.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx

from app.modules.sessions.schemas import SESSION_LIMIT
from app.modules.voice.providers.elevenlabs import AUDIO_FORMAT
from scripts.envfile import read_env

API = "https://api.elevenlabs.io/v1/convai/agents"

#: Their cap must sit above ours, not below it. If the provider hangs up first,
#: the relay reads it as a mid-room failure and settles as `provider_failure` —
#: which refunds the whole session. Every ordinary room would look like an
#: outage and cost us the minutes.
MAX_DURATION_SECONDS = int(SESSION_LIMIT.total_seconds()) + 180

#: Exactly what `to_event` consumes, and nothing else. An event we never read is
#: bandwidth on a latency-sensitive socket.
CLIENT_EVENTS = [
    "conversation_initiation_metadata",
    "audio",
    "interruption",
    "vad_score",
    "ping",
    # Not consumed yet. Enabled now because the Auditor needs it in Phase 3 and
    # it costs nothing to have flowing before then.
    "user_transcript",
    # Likewise unconsumed. This is what live captions are made of, and captions
    # are in the v1 accessibility floor (CLAUDE.md → WCAG 2.2 AA plus live
    # captions), not a later addition. One event per turn.
    #
    # Its streaming sibling `agent_chat_response_part` is deliberately absent:
    # captions do want the streamed form, since text arriving after the sentence
    # was spoken is a transcript rather than a caption — but it is the noisiest
    # event on a latency-sensitive socket and nothing reads it until the caption
    # work is real.
    "agent_response",
]

#: This list is authoritative, and `_merge` replaces it wholesale rather than
#: adding to it. An event enabled in the dashboard and not written down here is
#: removed the next time this script is applied.

#: Turn-taking, measured rather than guessed. See `docs/voice-latency.md`.
#:
#: `eager` is the whole latency story. Model and TTS together take 0.04s; the
#: rest is the provider deciding the speaker has finished, and eagerness moves
#: that from a 1.5–8.1s spread to 1.31–1.70s. The tightened *spread* is what was
#: bought — unpredictable pacing is what reads as broken, not a slow median.
#:
#: `turn_timeout` is a floor, not a cap: `turn_v3` is semantic and waits for a
#: finished thought, so 2.0 here was observed producing 4.2s endpointing at
#: `normal`. It is set low because there is no reason to make it high, not
#: because it bounds anything.
#:
#: The cost of `eager` is a panel more willing to talk over someone who is
#: thinking. That is the product's central tension rather than a tuning
#: detail (`Product.md` §1 against the churn risk of a first session that
#: destroys the user), and it was chosen deliberately.
TURN = {
    "turn_eagerness": "eager",
    "turn_timeout": 2.0,
    "soft_timeout_config": {
        # Covers the remaining ~1.4s with a sound rather than silence. A room
        # that goes quiet reads as broken; a room where someone murmurs reads as
        # someone considering what you just said.
        "timeout_seconds": 1.2,
        # PROVISIONAL. What a panelist murmurs is panel *tone*, which CLAUDE.md
        # reserves for the human and which belongs with the archetype work in
        # Phase 3 — a Margin-Obsessed CFO and a Growth Maximalist do not make
        # the same noise. These are deliberately flat and non-committal so they
        # commit to no character before that decision is made.
        "message": "Hm.",
        "additional_soft_timeout_messages": ["Mm.", "Right."],
        "randomize_fillers": True,
        # One per turn. A room that murmurs repeatedly is not considering, it is
        # stalling, and the user hears the difference immediately.
        "max_soft_timeouts_per_generation": 1,
        # The greeting is not a reply to anything, so there is nothing to be
        # seen considering.
        "disable_until_first_user_message": True,
    },
}

#: Enabled so Phase 3 can deliver archetypes per conversation. Overrides are
#: disabled by default and ElevenLabs throws on one that was never allowed, so
#: this must be set before the first archetype ships, not with it.
OVERRIDES = {
    "agent": {"prompt": {"prompt": True}, "first_message": True},
    "tts": {"voice_id": True},
}


def _merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge, so a partial update cannot silently drop a sibling key."""
    merged = dict(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def required_config() -> dict[str, Any]:
    return {
        "conversation_config": {
            "tts": {"agent_output_audio_format": AUDIO_FORMAT},
            "asr": {"user_input_audio_format": AUDIO_FORMAT},
            "turn": TURN,
            "conversation": {
                "text_only": False,
                "max_duration_seconds": MAX_DURATION_SECONDS,
                "client_events": CLIENT_EVENTS,
            },
        },
        "platform_settings": {
            "overrides": {"conversation_config_override": OVERRIDES}
        },
    }


def main() -> None:
    key, agent_id = read_env("ELEVENLABS_API_KEY"), read_env("ELEVENLABS_AGENT_ID")
    headers = {"xi-api-key": key}

    current = httpx.get(f"{API}/{agent_id}", headers=headers, timeout=20.0)
    current.raise_for_status()
    body = current.json()

    conv = body.get("conversation_config", {})
    print("current:")
    print(f"  agent_output_audio_format = {conv.get('tts', {}).get('agent_output_audio_format')!r}")
    print(f"  user_input_audio_format   = {conv.get('asr', {}).get('user_input_audio_format')!r}")
    print(f"  max_duration_seconds      = {conv.get('conversation', {}).get('max_duration_seconds')!r}")
    print(f"  client_events             = {conv.get('conversation', {}).get('client_events')}")
    turn = conv.get("turn", {})
    print(f"  turn_eagerness            = {turn.get('turn_eagerness')!r}")
    print(f"  turn_timeout              = {turn.get('turn_timeout')!r}")
    print(f"  soft_timeout              = {turn.get('soft_timeout_config', {}).get('timeout_seconds')!r}")

    print("\nrequired:")
    print(f"  audio formats             = {AUDIO_FORMAT!r} (both)")
    print(f"  max_duration_seconds      = {MAX_DURATION_SECONDS} (our cap is {int(SESSION_LIMIT.total_seconds())}s)")
    print(f"  client_events             = {CLIENT_EVENTS}")
    print(f"  turn                      = {TURN['turn_eagerness']!r}, "
          f"timeout {TURN['turn_timeout']}, "
          f"soft {TURN['soft_timeout_config']['timeout_seconds']}s")

    if "--apply" not in sys.argv:
        print("\ndry run — re-run with --apply to write these.")
        return

    payload = _merge(
        {
            "conversation_config": conv,
            "platform_settings": body.get("platform_settings", {}),
        },
        required_config(),
    )
    response = httpx.patch(
        f"{API}/{agent_id}", headers=headers, json=payload, timeout=20.0
    )
    if response.status_code >= 400:
        print(f"\nHTTP {response.status_code}")
        print(response.text[:800])
        raise SystemExit(1)

    after = httpx.get(f"{API}/{agent_id}", headers=headers, timeout=20.0).json()
    check = after.get("conversation_config", {})
    print("\napplied:")
    print(json.dumps(check.get("conversation", {}), indent=2)[:600])
    print(f"  tts format = {check.get('tts', {}).get('agent_output_audio_format')!r}")
    print(f"  asr format = {check.get('asr', {}).get('user_input_audio_format')!r}")


if __name__ == "__main__":
    main()
