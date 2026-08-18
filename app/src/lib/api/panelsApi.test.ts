import { SignedOut } from '../auth/session';
import { createPanelsApi } from './panelsApi';

/**
 * The catalogue, over HTTP.
 *
 * Thin, like the others. What matters here is that the roster is *fetched* and
 * never shipped inside the app: an archetype added on the server would
 * otherwise need an app release, and the two lists could disagree with nobody
 * noticing — the failure `MaterialLimits` already refused for the tier table.
 */
function apiReturning(status: number, body: unknown) {
  const calls: { url: string; headers?: Record<string, string> }[] = [];

  const fetcher = async (url: string, init: RequestInit) => {
    calls.push({ url, headers: init.headers as Record<string, string> });
    return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
  };

  return {
    api: createPanelsApi({
      baseUrl: 'https://api.example',
      fetch: fetcher as typeof fetch,
      accessToken: async () => 'access-1',
    }),
    calls,
  };
}

const CATALOGUE = {
  archetypes: [{ name: 'cfo', title: 'The CFO', blurb: 'Unimpressed.' }],
  seated: ['cfo', 'champion'],
  seats: 3,
  may_author: false,
  upgrade_seats: 5,
  difficulty: 2,
  hardest: 3,
};

it('fetches the roster and the caps in one request', async () => {
  // One call, because they are read at the same moment by the same screen —
  // the reason the seat count and the rung ride the catalogue rather than
  // sitting on endpoints of their own.
  const { api, calls } = apiReturning(200, CATALOGUE);

  await expect(api.catalogue()).resolves.toEqual({
    archetypes: [{ name: 'cfo', title: 'The CFO', blurb: 'Unimpressed.' }],
    seated: ['cfo', 'champion'],
    seats: 3,
    mayAuthor: false,
    upgradeSeats: 5,
    difficulty: 2,
    hardest: 3,
  });

  expect(calls).toEqual([
    {
      url: 'https://api.example/v1/archetypes',
      headers: { Authorization: 'Bearer access-1' },
    },
  ]);
});

it('reports a 401 as the session being over', async () => {
  const { api } = apiReturning(401, {});

  await expect(api.catalogue()).rejects.toBeInstanceOf(SignedOut);
});

it('sends a chosen rung as the number the contract names', async () => {
  const { api, calls } = apiReturning(200, { difficulty: 3 });

  await api.chooseDifficulty(3);

  expect(calls[0].url).toBe('https://api.example/v1/me/difficulty');
});


it('carries the seated room back in the order the server put it in', async () => {
  // The reveal. `docs/onboarding.md` warns that a reveal backed by a survey
  // which changed nothing is "a promise the first session immediately
  // contradicts" — so the order matters as much as the membership: the server
  // seats archetypes in this sequence and chair one really does speak first.
  const { api } = apiReturning(200, { ...CATALOGUE, seated: ['risk_officer', 'cfo'] });

  await expect(api.catalogue()).resolves.toMatchObject({
    seated: ['risk_officer', 'cfo'],
  });
});

it('reads a server that has not shipped the reveal yet as an empty room', async () => {
  // Belt and braces against a client newer than the API it is pointed at — a
  // missing field would otherwise be `undefined` where a screen maps over an
  // array, which crashes the setup screen rather than degrading it.
  const withoutSeated = { ...CATALOGUE };
  delete (withoutSeated as { seated?: string[] }).seated;

  const { api } = apiReturning(200, withoutSeated);

  await expect(api.catalogue()).resolves.toMatchObject({ seated: [] });
});
