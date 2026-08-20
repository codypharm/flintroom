import {
  NotYourPlan,
  TitleAlreadyUsed,
  createArchetypesApi,
} from './archetypesApi';
import { SignedOut } from '../auth/session';

const A_DRAFT = {
  title: 'The Board Chair',
  persona: 'Unimpressed by anything that is not a number.',
  domains: ['margin'],
  voice: null,
};

const A_ROW = { ...A_DRAFT, name: 'custom:0191d4c2' };

function api(reply: (url: string, init?: RequestInit) => Response) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const client = createArchetypesApi({
    baseUrl: 'https://api.test',
    accessToken: async () => 'a-token',
    fetch: (async (url, init) => {
      calls.push({ url: String(url), init });
      return reply(String(url), init);
    }) as typeof fetch,
  });
  return { client, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

it('writes a panelist and reads the minted name back', async () => {
  const { client, calls } = api(() => json(A_ROW, 201));

  const written = await client.write(A_DRAFT);

  expect(written.name).toBe('custom:0191d4c2');
  expect(calls[0].init?.method).toBe('POST');
});

it('takes the name from the answer, not from the request', async () => {
  // A panelist that has been in a room is replaced rather than edited, so old
  // rooms keep pointing at the text that was actually in them. A client that
  // echoed the name it sent would hold a stale one and seat the wrong row.
  const { client } = api(() => json({ ...A_ROW, name: 'custom:replacement' }));

  const edited = await client.revise('custom:0191d4c2', A_DRAFT);

  expect(edited.name).toBe('custom:replacement');
});

it('names the refusal a form can do something about', async () => {
  const { client } = api(() =>
    json({ error: { code: 'title_already_used', message: 'x' } }, 422)
  );

  await expect(client.write(A_DRAFT)).rejects.toBeInstanceOf(TitleAlreadyUsed);
});

it('tells a plan refusal apart from a bad field', async () => {
  // Both are the user being stopped, and only one is about what they typed.
  const { client } = api(() => json({ error: { code: 'x' } }, 403));

  await expect(client.write(A_DRAFT)).rejects.toBeInstanceOf(NotYourPlan);
});

it('leaves a 422 that is not about the title as an ordinary failure', async () => {
  // A too-long persona is also a 422. Branching on the status rather than the
  // code would put "you already have a panelist with that name" under the wrong
  // field.
  const { client } = api(() => json({ error: { code: 'validation_error' } }, 422));

  await expect(client.write(A_DRAFT)).rejects.not.toBeInstanceOf(TitleAlreadyUsed);
});

it('lets the gate hear a signed-out request', async () => {
  const { client } = api(() => json({}, 401));

  await expect(client.mine()).rejects.toBeInstanceOf(SignedOut);
});

it('retires one by name and expects no body', async () => {
  const { client, calls } = api(() => new Response(null, { status: 204 }));

  await client.retire('custom:0191d4c2');

  expect(calls[0].init?.method).toBe('DELETE');
  expect(calls[0].url).toContain('custom%3A0191d4c2');
});
