import { Link, router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Progress } from '../../components/modules/Progress';
import { createProgressApi, type Progress as Read } from '../../lib/api/progressApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { color, radius, space, type } from '../../theme/tokens';

const progress = createProgressApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/**
 * The front door.
 *
 * One job, and the tab bar is what finally lets it have one: **start a room.**
 * Until the Library existed this screen was a scaffold's list of links, because
 * there was nowhere else for a link to live. Now Library and Settings are
 * destinations in the bar, and what is left here is the action — HIG puts
 * actions on screens and destinations in the bar, which is the whole reason
 * Start is not a fourth tab.
 *
 * **What `design-guide/home/` has that is not here, and why.** A "3-day
 * streak", rejected outright in `docs/onboarding.md`. A "120 Tokens" counter,
 * retired for minutes — and §4.6 forbids a depleting counter regardless. An
 * "Avg. Likelihood 72%" with a bar chart, named in `Product.md:419` as a retired
 * decision. And cards for an "Investment Verdict" screen that no longer exists.
 * Strip the retired content and that mockup is one primary control, which is
 * what this is.
 *
 * The chart shape in that mockup was the one reusable thing, and it belongs to
 * the progress surface rather than to this screen — see #84, where it lands
 * once there is more than one room to compare.
 */
export default function HomeScreen() {
  const [read, setRead] = useState<Read | null>(null);

  /**
   * Re-read on every visit, not once on mount.
   *
   * This is a tab, so it is not unmounted when somebody leaves it — and the
   * one journey that changes what it says is exactly the one that leaves and
   * comes back: start a room, be interrogated, open the debrief, return. A
   * mount effect would show the state before the room they just ran.
   *
   * Failures are silent, and this is the one screen where that is right. The
   * progress block is a reason to start a room, not the way to start one; a
   * refusal drawn over the primary control would break the screen's actual job
   * over a sentence nobody asked for.
   */
  useFocusEffect(
    useCallback(() => {
      let live = true;

      progress
        .read()
        .then((theirs) => {
          if (live) setRead(theirs);
        })
        .catch(() => undefined);

      return () => {
        live = false;
      };
    }, [])
  );

  return (
    <SafeAreaView style={styles.screen} edges={['top']}>
      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.opening}>
          <Text style={styles.title}>Flintroom</Text>
          <Text style={styles.standfirst}>
            The room that grills you before the room that matters.
          </Text>
        </View>

        {/*
          Above the control, because it is the reason to press it. Drawn only
          once there is something true to say — a block that said "nothing yet"
          on a first launch would put an absence where the product's whole
          promise should be.
        */}
        {read && read.rooms.length > 0 && (
          <View style={styles.progress}>
            <Progress rooms={read.rooms} habits={read.habits} askers={read.askers} />
          </View>
        )}

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Start a room"
          onPress={() => router.push('/setup')}
          style={({ pressed }) => [styles.start, pressed && styles.pressed]}
        >
          <Text style={styles.startLabel}>Start a room</Text>
        </Pressable>

        {/*
          The instruments, kept and demoted rather than deleted.

          `/echo-spike` measures acoustic echo on a device and `/disclosure`
          shows a sheet that only appears once per account in the real flow —
          both are the only way to reach those on a phone, and #78 is still
          open. `/onboarding` is a real destination that the app does not yet
          route to on a first launch.

          Under a heading that says what they are, so nobody mistakes an
          instrument for a feature.
        */}
        <View style={styles.bench}>
          <Text style={styles.benchHeading}>On the bench</Text>
          <Link href="/onboarding" style={styles.link}>
            Onboarding
          </Link>
          <Link href="/echo-spike" style={styles.link}>
            Echo spike
          </Link>
          <Link href="/disclosure" style={styles.link}>
            Recording disclosure
          </Link>
          <Link href="/prep-sheet" style={styles.link}>
            Prep sheet
          </Link>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.surface },
  content: { padding: space.screen, paddingBottom: space.major },

  /** Space above the title rather than a hero: the control is the point. */
  opening: { paddingTop: space.section },
  title: { ...type.headlineLg, color: color.onSurface },
  standfirst: {
    ...type.bodyLg,
    color: color.onSurfaceVariant,
    marginTop: space.snug,
  },

  progress: { marginTop: space.section },

  start: {
    alignSelf: 'flex-start',
    marginTop: space.section,
    paddingVertical: space.base,
    paddingHorizontal: space.section,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  startLabel: { ...type.headlineSm, color: color.surface },
  pressed: { opacity: 0.6 },

  bench: { marginTop: space.major },
  benchHeading: {
    ...type.labelLg,
    color: color.onSurfaceVariant,
    marginBottom: space.tight,
  },
  link: {
    ...type.bodyMd,
    color: color.primary,
    paddingVertical: space.tight,
  },
});
