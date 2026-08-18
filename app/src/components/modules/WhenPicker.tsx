import { useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { asIsoDate, fromIsoDate, WINDOW } from '../../lib/onboarding/when';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Asking when the room happens, with each platform's own calendar.
 *
 * `@expo/ui` does not wrap one picker — it exposes two different things.
 * Compose gives a `DatePickerDialog`, a real modal that confirms or dismisses
 * itself. SwiftUI gives an inline `DatePicker` that renders where it is put and
 * has no presentation of its own. Papering that over with a single lowest-
 * common-denominator control would mean shipping a non-native calendar to both,
 * so this component is the seam and each side gets what its users recognise.
 *
 * **The native modules are loaded lazily, inside the branch that uses them.**
 * `@expo/ui/swift-ui` calls `requireNativeView` at module scope, so a static
 * import of it would run on Android — asking for an iOS view manager that is
 * not there. `import type` is erased at compile time and costs nothing; the
 * `require` only ever runs on the platform that can answer it.
 *
 * Clearing is not here. Both native pickers confirm or cancel, and cancel is
 * not "not sure yet" — so the row in `TablePlan` owns going back to no date,
 * where it can be a control rather than a gesture nobody would find.
 */
export interface WhenPickerProps {
  /** The date already chosen, or null. Where the picker opens. */
  value: string | null;
  /** A date was confirmed, as `YYYY-MM-DD` read off the local wall clock. */
  onPick: (iso: string) => void;
  /** Dismissed with nothing chosen. The plan is unchanged. */
  onClose: () => void;
}

export function WhenPicker(props: WhenPickerProps) {
  return Platform.OS === 'android' ? <Compose {...props} /> : <Cupertino {...props} />;
}

/**
 * Android: Material's own dialog, which owns its buttons and its dismissal.
 *
 * `variant="input"` is left off deliberately — the toggle to type a date is
 * offered by default, and somebody with a date three months out will want it.
 */
function Compose({ value, onPick, onClose }: WhenPickerProps) {
  const { DatePickerDialog } = require('@expo/ui/jetpack-compose') as
    typeof import('@expo/ui/jetpack-compose');
  const { Host } = require('@expo/ui/jetpack-compose') as
    typeof import('@expo/ui/jetpack-compose');

  const window = WINDOW();

  return (
    <Host style={styles.hidden}>
      <DatePickerDialog
        initialDate={value ?? asIsoDate(window.start)}
        selectableDates={window}
        color={color.primary}
        confirmButtonLabel="Set the date"
        dismissButtonLabel="Cancel"
        onDateSelected={(date) => onPick(asIsoDate(date))}
        onDismissRequest={onClose}
      />
    </Host>
  );
}

/**
 * iOS: the graphical calendar, in a sheet this app draws.
 *
 * SwiftUI's `DatePicker` has no presentation of its own, so the sheet, the
 * dimming and the Done button are ours — which is also why they use the app's
 * tokens rather than a second visual language appearing at the bottom of one
 * screen.
 *
 * The choice is held locally and committed on Done rather than on every scroll.
 * A picker that wrote through on each turn of the wheel would have somebody
 * dismissing it and finding the plan already changed to a date they scrolled
 * past on the way.
 */
function Cupertino({ value, onPick, onClose }: WhenPickerProps) {
  const { DatePicker, Host } = require('@expo/ui/swift-ui') as
    typeof import('@expo/ui/swift-ui');

  const window = WINDOW();
  const [chosen, setChosen] = useState(fromIsoDate(value) ?? window.start);

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Close without setting a date"
        style={styles.scrim}
        onPress={onClose}
      />
      <View style={styles.sheet}>
        <Text style={styles.title} accessibilityRole="header">
          When is it?
        </Text>

        <Host matchContents style={styles.host}>
          <DatePicker
            selection={chosen}
            range={window}
            displayedComponents={['date']}
            onDateChange={setChosen}
          />
        </Host>

        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Set the date"
          onPress={() => onPick(asIsoDate(chosen))}
          style={({ pressed }) => [styles.done, pressed && styles.pressed]}
        >
          <Text style={styles.doneLabel}>Set the date</Text>
        </Pressable>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  // The Compose dialog renders in its own window, so the host it is declared in
  // needs no space in the layout — it must simply exist.
  hidden: { position: 'absolute', width: 0, height: 0 },

  // `color.onSurface` at 40%. A derived alpha rather than a new colour — the
  // token file holds no scrim, and a sheet with nothing dimmed behind it reads
  // as a panel that has landed on the screen rather than in front of it.
  scrim: { flex: 1, backgroundColor: `${color.onSurface}66` },
  sheet: {
    backgroundColor: color.card,
    borderTopLeftRadius: radius.container,
    borderTopRightRadius: radius.container,
    paddingHorizontal: space.screen,
    paddingTop: space.loose,
    paddingBottom: space.major,
    gap: space.base,
  },
  title: { ...type.headlineSm, color: color.onSurface },
  host: { alignSelf: 'stretch' },

  done: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: color.primary,
    borderRadius: radius.pill,
    paddingVertical: space.snug,
  },
  doneLabel: { ...type.labelLg, color: color.onPrimary },
  pressed: { opacity: 0.6 },
});
