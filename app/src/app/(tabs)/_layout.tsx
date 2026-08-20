import { MaterialIcons } from '@expo/vector-icons';
import { Tabs, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { StyleSheet } from 'react-native';

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
 * **The marks are Material Icons, which is what the mockups always specified.**
 * `design-guide/home/code.html` draws its bottom nav with
 * `material-symbols-outlined`, and this bar spent its life approximating that
 * with Views — because no icon set was installed, and `expo-symbols`, though a
 * dependency, is SF Symbols and so iOS-only.
 *
 * What that produced was a ring for Home whose docstring described a seat the
 * component never drew. Hand-drawing a house from two borders on a rotated
 * square was not better: the same mistake with more geometry.
 *
 * `@expo/vector-icons` is Expo's own package and ships the Material set as a
 * font, so these are real vectors at any size and identical on both platforms.
 * It replaces four hand-built components.
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
          tabBarIcon: ({ color: tint }) => <MaterialIcons name="home" size={MARK} color={tint} />,
        }}
      />
      <Tabs.Screen
        name="progress"
        options={{
          title: 'Progress',
          tabBarIcon: ({ color: tint }) => <MaterialIcons name="trending-up" size={MARK} color={tint} />,
        }}
      />
      <Tabs.Screen
        name="library"
        options={{
          title: 'Library',
          tabBarIcon: ({ color: tint }) => <MaterialIcons name="history" size={MARK} color={tint} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarIcon: ({ color: tint }) => <MaterialIcons name="settings" size={MARK} color={tint} />,
        }}
      />
    </Tabs>
  );
}

/** Both platforms' tab-bar convention, and what the glyphs are drawn for. */
const MARK = 24;

const styles = StyleSheet.create({
  bar: {
    backgroundColor: color.card,
    borderTopColor: color.hairline,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  label: { ...type.labelLg, fontSize: 11 },
});
