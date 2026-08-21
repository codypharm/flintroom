import { byQuestion, exchanged } from './resumed';
import type { CoachTurn, SparringAttempt } from '../api/debriefApi';

/**
 * What a resumed debrief screen is rebuilt from. #83.
 *
 * The bug was not in this arithmetic — there was no arithmetic, because the
 * screen never received the conversation at all. These guard the shape it is
 * put back into, which is where the next mistake would live.
 */

const turn = (heard: string, text: string, speech = ''): CoachTurn => ({
  heard,
  text,
  speech,
});

const attempt = (weakRank: number, at: number, said: string): SparringAttempt => ({
  ...turn(said, `Better: ${said}`),
  weakRank,
  attempt: at,
});

describe('exchanged', () => {
  it('renames the coach line to what the screen calls it', () => {
    // One word for "what the other party said" across the room and the
    // debrief. Two spellings is how two surfaces come to disagree.
    expect(exchanged(turn('Why was that weak?', 'You gave a feeling.'))).toEqual({
      heard: 'Why was that weak?',
      said: 'You gave a feeling.',
      speech: '',
    });
  });

  it('carries empty audio through rather than dropping the turn', () => {
    // A recalled turn always has empty speech: the read is what a backgrounded
    // phone repeats, and a spoken reply costs about a minute of live
    // interrogation. The words are the point; `Replay` draws nothing when
    // there is nothing to play.
    expect(exchanged(turn('a', 'b')).speech).toBe('');
  });
});

describe('byQuestion', () => {
  it('gathers every go at one question under it', () => {
    const gathered = byQuestion([
      attempt(0, 0, 'We grew a lot.'),
      attempt(0, 1, 'We went from four hundred to five sixty.'),
    ]);

    expect(gathered[0].map((made) => made.heard)).toEqual([
      'We grew a lot.',
      'We went from four hundred to five sixty.',
    ]);
  });

  it('keeps questions apart', () => {
    const gathered = byQuestion([attempt(0, 0, 'first'), attempt(2, 0, 'third')]);

    expect(Object.keys(gathered)).toEqual(['0', '2']);
    expect(gathered[2][0].heard).toBe('third');
  });

  it('preserves the order they were made in without sorting', () => {
    // The wire orders by rank then attempt. Sorting here would be a second
    // opinion about it, and a list that reshuffled between two reads would
    // move a screen that had not changed.
    const gathered = byQuestion([
      attempt(1, 0, 'first go'),
      attempt(1, 1, 'second go'),
      attempt(1, 2, 'third go'),
    ]);

    expect(gathered[1].map((made) => made.heard)).toEqual([
      'first go',
      'second go',
      'third go',
    ]);
  });

  it('leaves a question nobody sparred absent rather than empty', () => {
    // The screen already falls back to an empty list per rank, so inventing
    // keys here would be a second place that decides what "no attempts" means.
    expect(byQuestion([attempt(3, 0, 'only this one')])[0]).toBeUndefined();
  });

  it('reads a room nobody sparred in as nothing at all', () => {
    expect(byQuestion([])).toEqual({});
  });
});
