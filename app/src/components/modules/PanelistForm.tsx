import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

import { type ArchetypeDraft, type MyArchetype } from '../../lib/api/archetypesApi';

/** The server's cap on a persona, mirrored so it is stated before submission. */
const PERSONA_LIMIT = 400;
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
  /** The stored value — an identifier, never shown. */
  name: string;
  /** What a person reads. */
  label: string;
  /** What it sounds like. The names alone are unchoosable. */
  sounds: string;
}

export interface DomainOffer {
  /** The routing key. What the API takes back. */
  name: string;
  /**
   * What a person reads.
   *
   * `defensibility` on a chip is a column name on a screen. The audience knows
   * `margin` and `runway` — flattening those would be worse than leaving them —
   * but nobody can rank `proof`, `references` and `resilience` against each
   * other on sight, which is the choice that decides when their panelist
   * interrupts.
   */
  label: string;
}

export interface PanelistFormProps {
  /** Every claim domain the server routes on, from the catalogue. */
  domains: DomainOffer[];
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
  const missing = whatIsMissing(title, persona, owned);

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
        {existing ? 'Edit this panelist' : 'Write one panelist'}
      </Text>

      {/*
        **"What do you call them?" was here and it asked for a nickname.**
        Reported as unclear, and it was: the field is the *role* — what the card,
        the transcript and the Library call this panelist — and "what do you call
        them" is the question you ask about somebody you already know.

        It was also a near-duplicate of the next one. "What do you call them?"
        and "Who are they?" both read as identity, with nothing saying the first
        is one line and the second a paragraph. Role, then character, is a
        ladder; two questions about identity is a form asking twice.

        **And it made a form for one person read as a form for several.** Every
        question here says "they" — correctly, because a panelist has no gender
        to assume — but four of them in a row, one screen away from "Your
        panelists", reads as configuring a group. Naming one role in the first
        question gives every pronoun after it an antecedent that is obviously
        one person.
      */}
      <Field
        label="What is their role?"
        // The examples, plus where it turns up. The hint used to say "a role,
        // the way the others are", which restated the label — helper text
        // answers the question the control raises, and the question here is
        // whether this is a private note or something you will be reading later.
        hint="One person: The Board Chair, The Regulator. It is what the transcript will call them."
        value={title}
        onChange={setTitle}
        busy={busy}
      />

      <Field
        label="Who are they?"
        // The register is the whole guard here (§6), and the placeholder is what
        // carries it — a manner, in the shape the shipped eight are written in.
        //
        // The second sentence used to read "the panel is built from roles, not
        // from people", which is a rule about the product rather than help with
        // the field, and naming people is a poor way to stop somebody thinking
        // about one. What replaces it says why the field is worth effort.
        hint="How they behave in a room. It is all they will know about who they are."
        placeholder="Unimpressed by anything that isn't a number. Asks one question at a time."
        value={persona}
        onChange={setPersona}
        busy={busy}
        long
        // Stated by the control rather than by a refusal. Without it, going over
        // arrives as a 422 rendered as "that did not save", which names neither
        // the field nor the reason — a requirement announced after submission.
        limit={PERSONA_LIMIT}
      />

      <Text style={styles.label} accessibilityRole="header">
        What do they go after?
      </Text>
      {/* What it is, then the cap. A constraint stated before somebody knows
          what they are choosing is a number with nothing to attach to. */}
      <Text style={styles.hint}>
        This is what decides when they interrupt. Pick up to {MOST_DOMAINS}.
      </Text>
      <View style={styles.chips}>
        {domains.map((domain) => (
          <Chip
            key={domain.name}
            label={domain.label}
            chosen={owned.includes(domain.name)}
            disabled={
              busy ||
              (owned.length >= MOST_DOMAINS && !owned.includes(domain.name))
            }
            onPress={() => toggle(domain.name)}
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
            label={offer.label}
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

      {/* Said, not implied. `PanelSetup.holdingUpStart` already worked this
          way — "a disabled button with no reason is the failure this exists to
          prevent" — and this form was the one screen in the product still
          leaving somebody to guess which field it was waiting on.

          Polite rather than an alert: nothing has failed, and interrupting a
          screen reader mid-form to say a field is still empty would be the app
          nagging somebody who is still typing. */}
      {missing !== null && (
        <Text style={styles.missing} accessibilityLiveRegion="polite">
          {missing}
        </Text>
      )}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Save this panelist"
        accessibilityState={{ disabled: busy || missing !== null }}
        disabled={busy || missing !== null}
        onPress={() =>
          onSave({ title: title.trim(), persona: persona.trim(), domains: owned, voice })
        }
        style={({ pressed }) => [
          styles.save,
          pressed && styles.pressed,
          (busy || missing !== null) && styles.dim,
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
        {/* Named, and named the same way twice: the visible label and the
            accessible one must not disagree about what a control does. */}
        <Text style={styles.cancelLabel}>Leave without saving</Text>
      </Pressable>
    </ScrollView>
  );
}

/**
 * Why Save cannot be pressed yet, or null when it can.
 *
 * A sentence rather than a boolean, exactly as `PanelSetup.holdingUpStart`
 * decided: *"a disabled button with no reason is the failure this exists to
 * prevent."* One product should not have one screen that explains itself and
 * another that does not.
 *
 * One thing at a time, in the order the form asks for it. Listing all three
 * shortfalls at once is a screen telling somebody who has filled in nothing
 * that they have filled in nothing.
 */
function whatIsMissing(
  title: string,
  persona: string,
  owned: string[]
): string | null {
  if (title.trim() === '') return 'Give them a name to be called by.';
  if (persona.trim() === '') return 'Say who they are.';
  if (owned.length === 0) {
    // The one worth explaining rather than naming. A panelist with no domains
    // would be seated and simply never catch anything, and its author would
    // have no way to find out why.
    return 'Pick what they go after, or they will never interrupt.';
  }
  return null;
}

function Field({
  label,
  hint,
  placeholder,
  value,
  onChange,
  busy,
  long = false,
  limit,
}: {
  label: string;
  hint: string;
  placeholder?: string;
  value: string;
  onChange: (next: string) => void;
  busy: boolean;
  long?: boolean;
  /** The server's cap, enforced here so it is never news after a save. */
  limit?: number;
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
        maxLength={limit}
        style={[styles.input, long && styles.long]}
      />
      {/* Only near the end. A counter from the first keystroke turns a
          description into a word budget, and this field wants somebody
          thinking about a person rather than about a number. */}
      {limit !== undefined && value.length > limit * 0.8 && (
        <Text style={styles.hint}>{limit - value.length} characters left.</Text>
      )}
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
  // Not `danger`. Nothing has failed — a form still being filled in is not an
  // error, and colouring it as one is how an interface teaches people to
  // distrust its own red.
  missing: { ...type.bodyMd, color: color.onSurfaceVariant, marginBottom: space.snug },

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
