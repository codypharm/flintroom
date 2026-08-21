import { nameFromDeck } from './deckName';

/**
 * Naming a rehearsal after the deck it is about.
 *
 * The field is optional and optional fields get skipped, so without a
 * suggestion most rehearsals stay headed by a date — the heading the name was
 * built to replace. What makes a derived name allowable is that it lands in the
 * field on the setup screen rather than in a heading afterwards: it is accepted,
 * edited or cleared before the room opens, so nobody ends up with a label they
 * cannot correct.
 */

it('says what somebody would say out loud', () => {
  expect(nameFromDeck('Q3 Board Readout.pdf')).toBe('Q3 Board Readout');
});

it('spells a filesystem separator as a space', () => {
  // Underscores and dots are how a filename writes a space. Hyphens are left
  // alone, because in a title a hyphen usually is one.
  expect(nameFromDeck('q3_board_readout.pptx')).toBe('q3 board readout');
  expect(nameFromDeck('series-b-narrative.pdf')).toBe('series-b-narrative');
});

it('leaves version noise where the person can see it', () => {
  // Stripping "v4" and "FINAL" was considered and refused: "Q4 final" is a real
  // thing to call a rehearsal, and a cleverer rule deletes words somebody meant.
  // This is a suggestion sitting in an editable field, not a stored label.
  expect(nameFromDeck('Q3 Board Readout v4 FINAL.pdf')).toBe('Q3 Board Readout v4 FINAL');
});

it('drops only the last extension', () => {
  // A dotted name is common and the earlier dots are separators, not suffixes.
  expect(nameFromDeck('2026.08.board.pdf')).toBe('2026 08 board');
});

it('suggests nothing when there is nothing to suggest', () => {
  // Null rather than an empty string, so the caller has one thing to check.
  expect(nameFromDeck('.pdf')).toBeNull();
  expect(nameFromDeck('___.pdf')).toBeNull();
});

it('will not suggest more than the server will store', () => {
  // The field, the schema and the column all stop at eighty. A suggestion the
  // server would refuse is a room that will not open for a reason nobody typed.
  expect(nameFromDeck(`${'a'.repeat(200)}.pdf`)).toHaveLength(80);
});
