import { Tabs, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet, View, type ColorValue } from 'react-native';

import { createBalanceApi, type Held } from '../../lib/api/balanceApi';
import { API_BASE_URL, auth } from '../../lib/auth';
import { TopBar } from '../../components/ui/TopBar';
import { color, space, type } from '../../theme/tokens';

const balance = createBalanceApi({
  baseUrl: API_BASE_URL,
  accessToken: () => auth.accessToken(),
});

/**
 * The three places you can be.
 *
 * A tab bar at last, and only now: `CLAUDE.md` puts one here for top-level
 * sections, and until this week the app had exactly one — a room you start and
 * leave. What earned it is the Library, which is a *destination* rather than a
 * step in a flow, and which two things the architect asked for both land on:
 * running a past room again, and seeing whether you are getting better.
 *
 * **Four, and the fourth was earned rather than copied.** Progress began as a
 * caption on Home and the architect's verdict was that a caption is not a
 * record — the aim is to track performance across rooms, which is a
 * destination. The mockup's four are Home, Sessions, Library and Profile; these
 * are not those.
 *
 * **On the mockup's own four.** `design-guide/home/` and
 * `design-guide/library/` both draw Home, Sessions, Library and Profile.
 * Sessions and Library do the same job here, so Library keeps it — the
 * architect's own definition, "a browser for all past sessions in case you want
 * to view the detail of discussion or play it and listen to it". Profile is
 * Settings, which already exists.
 *
 * **Starting a room is not a tab.** It is the thing this product is for, and it
 * is an action rather than a place — HIG puts actions on screens and
 * destinations in the bar. It lives on Home as the primary control.
 *
 * **Screens under this bar claim only the top inset.** `edges={['top']}`, not
 * `['top', 'bottom']`: the bar itself sits in the bottom safe area and already
 * accounts for the home indicator, so a screen claiming it too pads twice and
 * leaves a band of ground above the tabs. The screens on the stack — the room,
 * the debrief, the prep sheet — still take both, because nothing is under them.
 *
 * The marks are drawn from Views, following `DeckAttach` and `SignInSheet`:
 * there is no icon library here, `expo-symbols` is SF Symbols and so iOS-only,
 * and a Unicode glyph standing in for an icon is a costume. Three shapes that
 * read at twenty-four points and mean something in every language this will
 * ship in.
 */
export default function TabsLayout() {
  const [held, setHeld] = useState<Held | null>(null);

  /**
   * The balance, read once for four screens.
   *
   * It used to be Home's alone, because Home was the only screen that drew it.
   * The bar is on all four now, so the fetch belongs here — the alternative is
   * four screens asking the same question and disagreeing for a beat whenever
   * one of them is stale.
   *
   * On focus rather than on mount: a room spends minutes and returns here, and
   * a bar still showing the pre-room figure is worse than one showing none.
   * Failures stay silent, as they were on Home. A refusal drawn across the app
   * bar would break every screen under it over a line nobody asked for.
   */
  useFocusEffect(
    useCallback(() => {
      let live = true;

      balance
        .read()
        .then((left) => {
          if (live) setHeld(left);
        })
        .catch(() => undefined);

      return () => {
        live = false;
      };
    }, [])
  );

  return (
    <Tabs
      screenOptions={{
        /**
         * The app's own bar, on every top-level screen.
         *
         * `header` rather than `headerShown: false` plus a view inside each
         * screen: handed to the navigator it is pinned above the content, so it
         * survives scrolling — which is the entire defect it fixes. Every
         * screen here begins with a title inside its own ScrollView, and those
         * titles stay: this bar carries the *product*, and they carry the
         * *screen*. `design-guide/library/code.html` draws exactly that pair.
         */
        header: () => <TopBar held={held} />,
        headerShown: true,
        tabBarActiveTintColor: color.primary,
        tabBarInactiveTintColor: color.onSurfaceVariant,
        tabBarStyle: styles.bar,
        tabBarLabelStyle: styles.label,
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color: tint }) => <House tint={tint} />,
        }}
      />
      <Tabs.Screen
        name="progress"
        options={{
          title: 'Progress',
          tabBarIcon: ({ color: tint }) => <Climb tint={tint} />,
        }}
      />
      <Tabs.Screen
        name="library"
        options={{
          title: 'Library',
          tabBarIcon: ({ color: tint }) => <Shelf tint={tint} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color: tint }) => <Dials tint={tint} />,
        }}
      />
    </Tabs>
  );
}

/**
 * What the bar hands a mark.
 *
 * `ColorValue` rather than `string`: React Native's own type admits an opaque
 * platform colour, and narrowing it here would be a lie that only compiles.
 */
interface Mark {
  tint: ColorValue;
}

/**
 * A house, because this tab is called Home and a tab bar is not the place to
 * be clever.
 *
 * It was a ring until 2026-08-20 — "the table seen from above, with the
 * presenter's seat at its edge". The seat was never drawn, so what shipped was
 * a bare circle beside three marks that read, and the architect asked for a
 * proper home icon. `design-guide/home/code.html` had it right all along: the
 * mockup's bottom nav uses Material Symbols `home`, a house.
 *
 * Outline rather than filled, unlike the mockup's `FILL 1`. The active tab is
 * already carrying tint; filling it as well would make Home the only mark that
 * changes weight and not just colour.
 */
function House({ tint }: Mark) {
  return (
    <View style={styles.mark}>
      <View style={[styles.roof, { borderColor: tint }]} />
      <View style={[styles.walls, { borderColor: tint }]} />
    </View>
  );
}

/** A run of rooms: bars rising left to right, which is what Progress draws. */
function Climb({ tint }: Mark) {
  return (
    <View style={[styles.mark, styles.climb]}>
      <View style={[styles.step, { height: 7, backgroundColor: tint }]} />
      <View style={[styles.step, { height: 12, backgroundColor: tint }]} />
      <View style={[styles.step, { height: 18, backgroundColor: tint }]} />
    </View>
  );
}

/** An archive: entries stacked down a page, which is what the Library draws. */
function Shelf({ tint }: Mark) {
  return (
    <View style={styles.mark}>
      <View style={[styles.rule, styles.long, { backgroundColor: tint }]} />
      <View style={[styles.rule, styles.long, { backgroundColor: tint }]} />
      <View style={[styles.rule, styles.short, { backgroundColor: tint }]} />
    </View>
  );
}

/** Two tracks with their handles at different points — a control, not a cog. */
function Dials({ tint }: Mark) {
  return (
    <View style={styles.mark}>
      <View style={styles.track}>
        <View style={[styles.rule, styles.long, { backgroundColor: tint }]} />
        <View style={[styles.handle, styles.handleLeft, { backgroundColor: tint }]} />
      </View>
      <View style={styles.track}>
        <View style={[styles.rule, styles.long, { backgroundColor: tint }]} />
        <View style={[styles.handle, styles.handleRight, { backgroundColor: tint }]} />
      </View>
    </View>
  );
}

const MARK = 24;

const styles = StyleSheet.create({
  bar: {
    backgroundColor: color.card,
    borderTopColor: color.hairline,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  label: { ...type.labelLg, fontSize: 11 },

  mark: {
    width: MARK,
    height: MARK,
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.hair,
  },

  /**
   * Two adjacent borders on a square, turned to stand on its point.
   *
   * A transform does not change layout, so this still occupies 12pt in the
   * column while the drawn peak spans 12√2 ≈ 17pt corner to corner. That is
   * deliberate: the arms overhang `walls` by two points on each side, which is
   * an eave, and it is what stops the shape reading as a triangle balanced on
   * a box.
   */
  roof: {
    width: 12,
    height: 12,
    borderTopWidth: 2,
    borderLeftWidth: 2,
    transform: [{ rotate: '45deg' }],
    // The arm ends fall ~2.5pt below the un-rotated box. Without this the
    // walls start level with the box instead of level with the eaves, and the
    // roof floats.
    marginBottom: 2,
  },

  /** No top edge: the roof already closes it, and drawing both doubles it. */
  walls: {
    width: 13,
    height: 8,
    borderWidth: 2,
    borderTopWidth: 0,
  },

  /** The bars sit on a shared baseline, which is what makes them a climb. */
  climb: { flexDirection: 'row', alignItems: 'flex-end', gap: 3 },
  step: { width: 4, borderRadius: 1 },

  rule: { height: 2, borderRadius: 1 },
  long: { width: 18 },
  short: { width: 11 },

  /**
   * The handle sits *on* the track rather than beside it, which is what makes
   * two rules read as controls rather than as a shorter list.
   */
  track: { width: 18, justifyContent: 'center' },
  handle: {
    position: 'absolute',
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  handleLeft: { left: 3 },
  handleRight: { right: 3 },
});
