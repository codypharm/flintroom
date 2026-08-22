/**
 * How long a room runs, in seconds.
 *
 * Mirrors the server's `SESSION_LIMIT` (backend `sessions/schemas.py`), which
 * is what actually ends the room — this constant only *says* it: on the setup
 * screen before Start, and on the room's clock as the fixed side of
 * "4:32 / 12:00". If the server's cap ever changes, this is the one line the
 * app has to move with it; drifting apart shows up as a clock whose ceiling
 * the room does not honour.
 */
export const ROOM_LENGTH_SECONDS = 12 * 60;
