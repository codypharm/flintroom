import { router } from 'expo-router';

import { RecordingDisclosure } from '../components/modules/RecordingDisclosure';

/**
 * The recording disclosure, as a route so it can be seen.
 *
 * Presented as a `formSheet` — `_layout.tsx` carries the options, because Expo
 * Router reads presentation from the `Stack.Screen` that owns the route rather
 * than from the screen itself.
 *
 * **Standing in for a flow that does not exist yet.** `enterRoom`
 * (`src/lib/consent/entry.ts`) owns the real sequence — disclose, then the
 * microphone, then mint — and it needs a signed-in user and a session endpoint
 * to run. Sign-in has no screen, so until it does this route is the only way to
 * look at the sheet on a device, in the same spirit as the `Room` and
 * `Echo spike` links beside it.
 *
 * The window is hard-coded here and nowhere else. The real one is per tier and
 * arrives from `GET /v1/preferences/recording`; the component takes it as a
 * prop precisely so this screen cannot decide it, and 30 is the free tier's,
 * which is what an unsigned-in visitor would be.
 */
export default function DisclosureScreen() {
  return (
    <RecordingDisclosure
      retentionDays={30}
      onContinue={() => {
        // Dismiss, then push onto the stack underneath. Not `dismissTo` or
        // `replace`: both swap the *sheet's* route, so the room would render
        // inside a form sheet rather than replacing it.
        //
        // In the real flow this is `enterRoom`, and the microphone is settled
        // between these two steps. Here it goes straight through, because a
        // button labelled "Enter the room" that only closed a sheet was a
        // control naming an action it did not perform.
        router.dismiss();
        router.push('/room');
      }}
    />
  );
}
