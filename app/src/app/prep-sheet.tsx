import { Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { PrepSheet, type WeakAnswer } from '../components/modules/PrepSheet';
import { color } from '../theme/tokens';

/**
 * The prep sheet, on a room that has already been debriefed.
 *
 * **Not yet reading the API**, and the reason is the same one `settings.tsx`
 * gives rather than a shortcut: `GET /v1/sessions/{id}/debrief` needs a bearer
 * token the app cannot obtain, because sign-in has no screen. The room screen
 * works around that with a pasted development token; a prep sheet that did the
 * same would be an instrument rather than a destination.
 *
 * So this renders a session shaped like the ones the backend actually produces
 * — the room from `scripts/weakness.py`, whose findings were measured against a
 * live model rather than invented here. When sign-in lands, this file gains a
 * fetch and loses this comment.
 *
 * The sample is deliberately *mixed*: two findings that are the presenter's and
 * two that are not. A sample of four identical failings would let the fault
 * split — the one thing on this screen that must not be got wrong — go
 * unexercised every time somebody opens it.
 */

const MEASURED: WeakAnswer[] = [
  {
    ordinal: 1,
    question: 'What does it cost you to acquire a customer, and how long until that pays back?',
    askedBy: 'cfo',
    answer:
      'Acquisition cost is twelve hundred dollars, and a customer pays us a hundred and eighty a month, so payback lands around four months.',
    weakness: 'contradicted',
    why: 'At $180 a month, recovering $1,200 takes nearly seven months rather than four.',
  },
  {
    ordinal: 3,
    question: 'What happens to your latency at ten times the current load?',
    askedBy: 'technical_skeptic',
    answer: 'We are really excited about what is coming on the roadmap next quarter.',
    weakness: 'evasive',
    why: 'You deflected to the roadmap instead of answering about load.',
  },
  {
    ordinal: 5,
    question: 'How long does it take a new customer to see value?',
    askedBy: 'champion',
    answer: null,
    weakness: 'dismissed',
    why: 'Another panelist interrupted with a question about burn before you could answer.',
  },
  {
    ordinal: 12,
    question: 'What stops a competitor rebuilding this in a quarter?',
    askedBy: 'technical_skeptic',
    answer: null,
    weakness: 'not_reached',
    why: 'The session reached its time limit before you could answer this one.',
  },
];

export default function PrepSheetRoute() {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: color.surface }} edges={['bottom']}>
      <PrepSheet
        answers={MEASURED}
        onSpar={() => {
          // The endpoint exists — POST .../debrief/weak-answers/{rank}/attempts
          // — and needs a recorded clip and a token, neither of which this
          // screen can produce yet. Inert rather than faked: a re-try that
          // appeared to work and reached nothing would teach somebody an answer
          // nobody heard.
          Alert.alert('Not yet connected', 'Sparring needs sign-in and the microphone.');
        }}
        onShare={() => {
          // Rendering the view to an image and handing it to the native share
          // sheet is the whole of the export, and it drops the verbatim answers
          // on the way out. Deliberately not stubbed with a text share: the
          // point of the decision was what leaves the phone.
          Alert.alert('Not yet built', 'Export renders this to an image on device.');
        }}
      />
    </SafeAreaView>
  );
}
