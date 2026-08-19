import { Tabs } from 'expo-router';
import { StyleSheet, View, type ColorValue } from 'react-native';

import { color, space, type } from '../../theme/tokens';

/**
 * The three places you can be.
 *
 * A tab bar at last, and only now: `CLAUDE.md` puts one here for top-level
 * sections, and until this week the app had exactly one — a room you start and
 * leave. What earned it is the Library, which is a *destination* rather than a
 * step in a flow, and which two things the architect asked for both land on:
 * running a past room again, and seeing whether you are getting better.
 *
 * **Three, not the mockup's four.** `design-guide/home/` and
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
  return (
    <Tabs
      screenOptions={{
        // Every screen draws its own title, exactly as the root stack decided.
        // A bar header here would stack a second one above each.
        headerShown: false,
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
          tabBarIcon: ({ color: tint }) => <Table tint={tint} />,
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

/** The table, seen from above: a ring with the presenter's seat at its edge. */
function Table({ tint }: Mark) {
  return (
    <View style={styles.mark}>
      <View style={[styles.ring, { borderColor: tint }]} />
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

  ring: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
  },

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
