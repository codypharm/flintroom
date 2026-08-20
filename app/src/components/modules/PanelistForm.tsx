import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { type ArchetypeDraft, type MyArchetype } from '../../lib/api/archetypesApi';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Writing a panelist of your own.
 *
 * `docs/custom-archetypes.md` §0 says who supplies what, and this form is that
 * table made tappable: a title, one description, the domains they own, and a
 * voice they may skip. Everything else — the attack strategy, the opener, the
 * nudge, the name — is ours or absent, and none of it appears here.
 *
 * **The mockup gave the layout and none of the fields.**
 * `design-guide/create_custom_panelist/` asks for Panelist Name, Core Focus,
 * *Investment Stage*, Feedback Tone and instructions for an "AI investor"
 * during a "pitch review" — the retired pitch-only product (`Product.md` §9).
 * What survives is its shape: a header that goes back, labelled sections, a
 * textarea for the long field, small choices as rows of chips, one action at the
 * foot. What does not: the Upload Photo control, because portraits are
 * *"generated people, not photographs of anyone"* and a custom panelist wears
 * its own initials; and every field naming a stage or a tone, because a field is
 * a promise the same way a picker option is.
 *
 * **The domains are handed in, never hardcoded.** They are the Auditor's
 * routing key and the server refuses one it does not route on, so a list copied
 * into the app is a form offering choices the API rejects — with the refusal
 * landing on somebody who picked what we showed them.
 */

export interface VoiceOffer {
  name: string;
  /** What it sounds like. The names alone are unchoosable. */
  sounds: string;
}

export interface PanelistFormProps {
  /** Every claim domain the server routes on, from the catalogue. */
  domains: string[];
  voices: VoiceOffer[];
  /** The one being edited, or null when writing a new one. */
  existing: MyArchetype | null;
  busy: boolean;
  /** Said plainly, and never as "something went wrong". */
  refusal: string | null;
  onSave: (draft: ArchetypeDraft) => void;
  onCancel: () => void;
}

/** As many domains as one panelist may own — the server's own cap. */
const MOST_DOMAINS = 4;

export function PanelistForm({
  domains,
  voices,
  existing,
  busy,
  refusal,
  onSave,
  onCancel,
}: PanelistFormProps) {
  const [title, setTitle] = useState(existing?.title ?? '');
  const [persona, setPersona] = useState(existing?.persona ?? '');
  const [owned, setOwned] = useState<string[]>(existing?.domains ?? []);
  const [voice, setVoice] = useState<string | null>(existing?.voice ?? null);

  // Checked here as well as by the server, and the domain rule is the one worth
  // catching early: a panelist with none can never be the one an interruption
  // reaches, and nothing downstream would ever say so.
  const ready = title.trim() !== '' && persona.trim() !== '' && owned.length > 0;

  const toggle = (domain: string) =>
    setOwned((held) =>
      held.includes(domain)
        ? held.filter((one) => one !== domain)
        : held.length < MOST_DOMAINS
          ? [...held, domain]
          : held
    );

  return (
    <ScrollView
      style={styles.sheet}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title} accessibilityRole="header">
        {existing ? 'Edit this panelist' : 'Write a panelist'}
      </Text>

      <Field
        label="What do you call them?"
        hint="A role, the way the others are — The Board Chair, The Regulator."
        value={title}
        onChange={setTitle}
        busy={busy}
      />

      <Field
        label="Who are they?"
        // The register is the whole guard here (§6): a role, not a person. The
        // placeholder teaches that shape without a rule, which is the call
        // `TablePlan` made about listing situations — "a picker option is a
        // promise".
        hint="How they behave in a room. The panel is built from roles, not from people."
        placeholder="Unimpressed by anything that isn't a number. Asks one question at a time."
        value={persona}
        onChange={setPersona}
        busy={busy}
        long
      />

      <Text style={styles.label} accessibilityRole="header">
        What do they go after?
      </Text>
      <Text style={styles.hint}>
        Up to {MOST_DOMAINS}. This is what decides when they interrupt.
      </Text>
      <View style={styles.chips}>
        {domains.map((domain) => (
          <Chip
            key={domain}
            label={domain}
            chosen={owned.includes(domain)}
            disabled={busy || (owned.length >= MOST_DOMAINS && !owned.includes(domain))}
            onPress={() => toggle(domain)}
          />
        ))}
      </View>

      <Text style={styles.label} accessibilityRole="header">
        How do they sound?
      </Text>
      <View style={styles.voices}>
        {/* First and default. Casting is optional by decision — most people
            writing a panelist care about the argument it makes, not its
            timbre, and making them choose is a decision tax on the main path. */}
        <VoiceRow
          label="Pick one for me"
          sounds="We will use whichever voice is free in the room."
          chosen={voice === null}
          disabled={busy}
          onPress={() => setVoice(null)}
        />
        {voices.map((offer) => (
          <VoiceRow
            key={offer.name}
            label={offer.name}
            sounds={offer.sounds}
            chosen={voice === offer.name}
            disabled={busy}
            onPress={() => setVoice(offer.name)}
          />
        ))}
      </View>

      {refusal !== null && (
        <Text style={styles.refusal} accessibilityRole="alert">
          {refusal}
        </Text>
      )}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Save this panelist"
        accessibilityState={{ disabled: busy || !ready }}
        disabled={busy || !ready}
        onPress={() =>
          onSave({ title: title.trim(), persona: persona.trim(), domains: owned, voice })
        }
        style={({ pressed }) => [
          styles.save,
          pressed && styles.pressed,
          (busy || !ready) && styles.dim,
        ]}
      >
        <Text style={styles.saveLabel}>
          {existing ? 'Save changes' : 'Add to your panel'}
        </Text>
      </Pressable>

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Leave without saving"
        disabled={busy}
        onPress={onCancel}
        style={({ pressed }) => [styles.cancel, pressed && styles.pressed]}
      >
        <Text style={styles.cancelLabel}>Cancel</Text>
      </Pressable>
    </ScrollView>
  );
}

function Field({
  label,
  hint,
  placeholder,
  value,
  onChange,
  busy,
  long = false,
}: {
  label: string;
  hint: string;
  placeholder?: string;
  value: string;
  onChange: (next: string) => void;
  busy: boolean;
  long?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.label} accessibilityRole="header">
        {label}
      </Text>
      <Text style={styles.hint}>{hint}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChange}
        editable={!busy}
        placeholder={placeholder}
        placeholderTextColor={color.onSurfaceVariant}
        multiline={long}
        style={[styles.input, long && styles.long]}
      />
    </View>
  );
}

function Chip({
  label,
  chosen,
  disabled,
  onPress,
}: {
  label: string;
  chosen: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityLabel={label}
      accessibilityState={{ checked: chosen, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.chip,
        chosen && styles.chipChosen,
        pressed && styles.pressed,
        disabled && !chosen && styles.dim,
      ]}
    >
      <Text style={[styles.chipLabel, chosen && styles.chipLabelChosen]}>{label}</Text>
    </Pressable>
  );
}

function VoiceRow({
  label,
  sounds,
  chosen,
  disabled,
  onPress,
}: {
  label: string;
  sounds: string;
  chosen: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      // Both, because the name alone is unchoosable — "measured" and "smooth"
      // are the same word to somebody who has heard neither.
      accessibilityLabel={`${label}. ${sounds}`}
      accessibilityState={{ selected: chosen, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.voice, pressed && styles.pressed]}
    >
      {/* The same ring the chairs and the plan's options use: empty is
          available, filled is taken. One visual language for "a thing you
          choose" across the whole product. */}
      <View style={[styles.pick, chosen && styles.picked]} />
      <View style={styles.voiceWords}>
        <Text style={[styles.voiceName, chosen && styles.voiceChosen]}>{label}</Text>
        <Text style={styles.hint}>{sounds}</Text>
      </View>
    </Pressable>
  );
}

const PICK = 14;

const styles = StyleSheet.create({
  sheet: { flex: 1, backgroundColor: color.surface },
  content: {
    paddingHorizontal: space.screen,
    paddingTop: space.section,
    paddingBottom: space.major,
  },

  title: { ...type.headlineLg, color: color.onSurface, marginBottom: space.loose },

  field: { marginBottom: space.section },
  label: { ...type.headlineSm, color: color.onSurface },
  hint: { ...type.bodySm, color: color.onSurfaceVariant, marginTop: space.hair },

  input: {
    ...type.bodyLg,
    color: color.onSurface,
    backgroundColor: color.card,
    borderRadius: radius.control,
    paddingHorizontal: space.base,
    paddingVertical: space.snug,
    marginTop: space.snug,
    minHeight: 44,
  },
  long: { minHeight: 120, textAlignVertical: 'top' },

  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: space.tight,
    marginTop: space.snug,
    marginBottom: space.section,
  },
  chip: {
    minHeight: 44,
    justifyContent: 'center',
    paddingHorizontal: space.base,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: color.hairline,
    backgroundColor: color.card,
  },
  chipChosen: { backgroundColor: color.primary, borderColor: color.primary },
  chipLabel: { ...type.labelLg, color: color.onSurfaceVariant },
  chipLabelChosen: { color: color.onPrimary },

  voices: { marginTop: space.snug, marginBottom: space.section },
  voice: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 44,
    paddingVertical: space.snug,
  },
  voiceWords: { flex: 1 },
  voiceName: { ...type.bodyLg, color: color.onSurfaceVariant },
  voiceChosen: { color: color.primary },

  pick: {
    width: PICK,
    height: PICK,
    borderRadius: PICK / 2,
    borderWidth: 2,
    borderColor: color.hairline,
    backgroundColor: color.surface,
    marginRight: space.base,
  },
  picked: { backgroundColor: color.primary, borderColor: color.primary },

  refusal: { ...type.bodyMd, color: color.danger, marginBottom: space.snug },

  save: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: space.snug,
    borderRadius: radius.pill,
    backgroundColor: color.primary,
  },
  saveLabel: { ...type.labelLg, color: color.onPrimary },

  cancel: {
    minHeight: 44,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: space.snug,
  },
  cancelLabel: { ...type.labelLg, color: color.onSurfaceVariant },

  pressed: { opacity: 0.6 },
  dim: { opacity: 0.4 },
});
