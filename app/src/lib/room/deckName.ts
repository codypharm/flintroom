/**
 * A rehearsal's name, suggested from the deck it is grounded in.
 *
 * The naming field is optional, and optional fields get skipped — so without
 * this the common case is a rehearsal headed by "Started 11 August", which is
 * the useless heading the name exists to replace.
 *
 * **A suggestion, never a label.** The distinction that makes this allowable is
 * *where* it appears: a name applied behind somebody's back is one they cannot
 * correct, which is why nothing derives a heading from the panel or the
 * filename at render time. This puts the words in the field on the setup
 * screen, before Start, where they are accepted, edited or cleared. Nothing is
 * ever stored that was not on screen when the room opened.
 *
 * The filename survives the source document — `docs/ingestion.md` deletes the
 * file once extraction succeeds and keeps `materials.filename` — so this works
 * on a re-run months later.
 */

/** Matches the server's `REHEARSAL_NAME_LIMIT`. */
const LIMIT = 80;

/**
 * The deck's name, tidied just enough to read as a title.
 *
 * **Deliberately modest.** Stripping version noise — "v4", "FINAL", "(1)" — was
 * considered and refused: "Q4 final" is a real thing to call a rehearsal, and a
 * cleverer rule would quietly delete words somebody meant. The extension goes
 * because nobody says "dot pdf" out loud, and separators become spaces because
 * a filename is written for a filesystem. Everything else is left alone, in
 * front of the person who can fix it.
 *
 * Returns null when there is nothing worth suggesting, so the caller has one
 * thing to check rather than an empty string to notice.
 */
export function nameFromDeck(filename: string): string | null {
  const stem = filename.replace(/\.[^./\\]+$/, '');

  const said = stem
    // Underscores and dots are how a filesystem spells a space. Hyphens are
    // left, because a hyphen reads as a hyphen in a title and often is one.
    .replace(/[_.]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (said === '') return null;

  return said.length > LIMIT ? said.slice(0, LIMIT).trimEnd() : said;
}
