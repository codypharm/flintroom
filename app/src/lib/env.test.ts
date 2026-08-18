import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Environment variables have to be readable on a device, not only in Jest.
 *
 * Expo inlines `EXPO_PUBLIC_*` into the bundle by **textual substitution of dot
 * notation**. `process.env[name]` is never replaced and reads `undefined` on a
 * phone — while passing every unit test, because Jest runs in Node where
 * `process.env` is a real object populated at run time.
 *
 * That gap is why this is a source check rather than a behaviour test: there is
 * no runtime assertion that can tell the two apart off-device. It has now cost
 * the project twice — `room.tsx` carries the warning in a comment, and
 * `lib/auth/google.ts` made the same mistake anyway and failed on the first
 * simulator launch, reporting a variable as unset that was set.
 */

const SOURCE = join(__dirname, '..');

function everySourceFile(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);

    if (entry.isDirectory()) return everySourceFile(path);
    // Tests are excluded deliberately: they run in Node, never ship in a
    // bundle, and setting up an environment is the only way to test a guard
    // that reads one.
    if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return [];

    return [path];
  });
}

/**
 * Comments stripped first, and the first draft of this test needed it: the two
 * files that *warn* about dynamic access both quote the offending form, so a
 * naive scan reported the warnings as the offence.
 */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
}

it('never reads an environment variable in a way the bundler cannot inline', () => {
  const offenders = everySourceFile(SOURCE)
    .filter((path) =>
      /process\.env\s*\[/.test(withoutComments(readFileSync(path, 'utf8')))
    )
    .map((path) => path.slice(SOURCE.length + 1));

  expect(offenders).toEqual([]);
});
