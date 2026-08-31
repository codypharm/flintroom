import { readFileSync } from 'node:fs';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import waitlist from './waitlist.js';

/**
 * The waitlist function, which had no test until it broke in production.
 *
 * #113 added `"type": "module"` to `package.json` for Astro. That made every
 * `.js` in this package ESM, `module.exports` became an undefined reference,
 * and this handler threw on every invocation. `/api/waitlist` answered 500 on
 * the live site and nothing anywhere noticed, because nothing anywhere ran it:
 * no test imported it, `astro check` excludes `api/`, `astro dev` does not
 * serve it, and the build deliberately never touches it. The first execution
 * of this file, ever, was a real visitor's.
 *
 * Catching that class of break turned out to be harder than it looks, and the
 * second test below is the honest version. The short story: neither the import
 * at the top of this file nor a subprocess running Node's own loader goes red
 * against the broken file, because both this machine's Node and Vite are more
 * forgiving than whatever Vercel runs. So the check is on the source.
 *
 * No network. The two calls to Resend are stubbed, because what is being
 * proved is the handler's own decisions: who gets answered, with what, and
 * which failures are allowed to reach the visitor.
 */

function reply() {
  const seen = { code: 0, body: null };
  const response = {
    status(code) {
      seen.code = code;
      return response;
    },
    json(body) {
      seen.body = body;
      return response;
    },
  };
  return { seen, response };
}

const ok = () => ({ ok: true, status: 200 });

beforeEach(() => {
  process.env.RESEND_API_KEY = 'test-key';
  process.env.RESEND_AUDIENCE_ID = 'test-audience';
  vi.stubGlobal('fetch', vi.fn(async () => ok()));
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.RESEND_API_KEY;
  delete process.env.RESEND_AUDIENCE_ID;
});

describe('the module itself', () => {
  it('exposes a handler', () => {
    expect(typeof waitlist).toBe('function');
  });

  it('uses the module system its package declares', () => {
    // **A source assertion, and deliberately not a runtime one.** Two runtime
    // checks were written for this and both were measured against the broken
    // file; both stayed green. Vitest goes through Vite, which transpiles
    // CommonJS interop, so `module.exports = fn` still arrives above as a
    // default export. And Node 24 does not throw either — since 22.7 it
    // detects CommonJS syntax in a `"type": "module"` package and falls back,
    // so even shelling out to the real loader proves nothing on this machine.
    //
    // Which is the whole difficulty: the failure needs the runtime Vercel
    // happens to be on, and it cannot be reproduced here. So this checks the
    // thing that is true on every version — that a package declaring ESM does
    // not contain a file written as CommonJS. It is a lint rather than a test,
    // and it is the only form of this that would actually have gone red.
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    const source = readFileSync(new URL('./waitlist.js', import.meta.url), 'utf8');

    expect(pkg.type).toBe('module');
    expect(source).not.toMatch(/^\s*module\.exports\s*=/m);
    expect(source).not.toMatch(/\brequire\s*\(/);
    expect(source).toMatch(/^export default /m);
  });
});

describe('who gets turned away', () => {
  it('refuses anything that is not a POST', async () => {
    const { seen, response } = reply();

    await waitlist({ method: 'GET' }, response);

    expect(seen.code).toBe(405);
  });

  it('refuses an address that is not one', async () => {
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'nope' } }, response);

    expect(seen.code).toBe(422);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it('refuses an address long enough to be an attack', async () => {
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: `${'a'.repeat(250)}@b.co` } }, response);

    expect(seen.code).toBe(422);
  });

  it('survives a request with no body at all', async () => {
    const { seen, response } = reply();

    await waitlist({ method: 'POST' }, response);

    expect(seen.code).toBe(422);
  });
});

describe('the honeypot', () => {
  it('tells a bot it succeeded, and stores nothing', async () => {
    // Telling a bot it was caught only trains it. The field is invisible to a
    // person, so anything in it came from something that reads markup.
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co', company: 'Acme' } }, response);

    expect(seen.code).toBe(200);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});

describe('a real signup', () => {
  it('adds the contact and sends the welcome', async () => {
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co' } }, response);

    expect(seen.code).toBe(200);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it('reads a repeat signup as success, because it is a person checking', async () => {
    // Resend answers 422 for a contact it already holds. That is somebody
    // double-checking they are on the list, not a fault to report.
    vi.stubGlobal('fetch', vi.fn(async (url) =>
      String(url).includes('/contacts') ? { ok: false, status: 422 } : ok(),
    ));
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co' } }, response);

    expect(seen.code).toBe(200);
  });

  it('still succeeds when the welcome email is refused', async () => {
    // Best effort by design: a failed email must not undo a stored signup.
    vi.stubGlobal('fetch', vi.fn(async (url) =>
      String(url).includes('/emails') ? { ok: false, status: 500 } : ok(),
    ));
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co' } }, response);

    expect(seen.code).toBe(200);
  });

  it('fails when the contact itself cannot be stored', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co' } }, response);

    expect(seen.code).toBe(502);
  });
});

describe('when we are the ones misconfigured', () => {
  it('says try again rather than naming a vendor', async () => {
    // The same rule the backend follows: a provider failure never reaches the
    // visitor as a stack of vendor words.
    delete process.env.RESEND_API_KEY;
    const { seen, response } = reply();

    await waitlist({ method: 'POST', body: { email: 'a@b.co' } }, response);

    expect(seen.code).toBe(502);
    expect(JSON.stringify(seen.body).toLowerCase()).not.toContain('resend');
  });
});
