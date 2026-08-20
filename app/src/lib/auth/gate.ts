import type { WhoTheyAre } from '../api/meApi';
import { SignedOut } from './session';

/**
 * What a launch concludes, before anything is drawn.
 *
 * Pure and separate from the hook that calls it, because the risk here is the
 * mapping rather than the plumbing: each answer sends somebody to a different
 * screen, and getting one wrong either strands them or throws away a working
 * session.
 */

export type WhoIsThere =
  /** A good credential, and an account that has described a room. */
  | 'ready'
  /**
   * A good credential, and nothing said yet.
   *
   * Reachable on purpose since the survey moved behind sign-in: an account can
   * now exist with no situation, role or audience, which `docs/onboarding.md`
   * once refused and now records as a deliberate trade.
   */
  | 'undescribed'
  /** No credential, or one the server no longer accepts. */
  | 'signed out'
  /**
   * We could not find out.
   *
   * **Never collapsed into "signed out"**, which is the single most damaging
   * mistake available here: a phone loses its connection constantly, and
   * treating that as a dead credential discards a working session — including
   * a refresh token that cannot be recovered.
   */
  | 'unreachable';

export async function whoIsThere(read: () => Promise<WhoTheyAre>): Promise<WhoIsThere> {
  try {
    return (await read()).onboarded ? 'ready' : 'undescribed';
  } catch (error) {
    return error instanceof SignedOut ? 'signed out' : 'unreachable';
  }
}
