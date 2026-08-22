import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import type { AttachedMaterial, MaterialLimits } from '../../lib/api/materialsApi';
import { color, radius, space, type } from '../../theme/tokens';

/**
 * Attaching a deck, as a control that looks like one.
 *
 * What this replaced was a single text row inside the same card, with the same
 * two lines of type, the same padding and the same absence of any mark as the
 * eight archetype rows above it. Tapping one of those seats a panelist and
 * shows a chair number; tapping this one opens the operating system's file
 * browser. Identical shape, unrelated consequence, and nothing on screen
 * distinguishing them — which is the whole of why it was not intuitive.
 *
 * Three things fix that and they are all structural rather than decorative:
 *
 *   1. **A leading mark**, drawn rather than borrowed. It gives the section a
 *      shape the eye finds before it reads anything, and it is the only element
 *      on the screen that is not a row of text, so the row stops being one of
 *      eight identical things.
 *   2. **The state is in the mark's colour**, not only in a sentence. Hairline
 *      empty, primary once there is a deck, danger when it could not be read —
 *      legible from arm's length, which a grey caption is not.
 *   3. **The actions are named and separate.** Before, an attached deck could
 *      only be replaced by tapping the row again, which is invisible, and could
 *      not be removed at all.
 *
 * The mark is drawn from Views for the same reason the chevron in `SignInSheet`
 * is: there is no icon library in this app, `expo-symbols` is SF Symbols and so
 * iOS-only, and a Unicode glyph standing in for an icon is a costume. A page
 * with two ruled lines on it is a document in every visual language this
 * product will ship in.
 */
export interface DeckAttachProps {
  material: AttachedMaterial | null;
  /**
   * What this account may upload, or null while it is unknown.
   *
   * Null is a real state rather than a loading flicker: the limits call can
   * fail, and the formats are a fact about the product that should be said
   * anyway. Only the size comes from the tier.
   */
  limits: MaterialLimits | null;
  onAttach: () => void;
  onRemove: () => void;
}

export function DeckAttach({ material, limits, onAttach, onRemove }: DeckAttachProps) {
  const failed = material?.state === 'failed';
  const reading = material?.state === 'extracting';

  return (
    <View style={styles.card}>
      <Pressable
        // The whole face is the attach target when empty. Once a deck is on it
        // the face becomes a description and the actions below are the controls
        // — two ways to replace on a row this small is how somebody attaches a
        // second deck believing they swapped the first.
        //
        // So it stops being a button rather than becoming a disabled one. A
        // disabled control still announces itself, and it would announce the
        // same name as the real Replace sitting inches below it.
        accessibilityRole={material === null ? 'button' : undefined}
        accessibilityLabel={material === null ? 'Attach a deck' : undefined}
        onPress={material === null ? onAttach : undefined}
        disabled={material !== null}
        style={({ pressed }) => [styles.face, pressed && styles.pressed]}
      >
        <Mark tone={failed ? 'failed' : material ? 'held' : 'empty'} />

        <View style={styles.said}>
          <Text style={styles.title}>{material?.filename ?? 'Attach a deck'}</Text>
          <Text
            style={[styles.detail, failed && styles.wrong]}
            // An alert, because somebody who has been watching a spinner for a
            // minute needs to be told it stopped rather than discover it.
            accessibilityRole={failed ? 'alert' : undefined}
          >
            {says(material)}
          </Text>
        </View>

        {reading && (
          <ActivityIndicator color={color.primary} accessibilityLabel="Reading your deck" />
        )}

        {/*
          **Only while the face is a target**, which is the rule `AuthorRow`
          two inches down this screen already follows and `TablePlan` states
          from the other side: a chevron on a statement is a lie about what a
          tap does. With a deck attached this face stops being a button and
          Replace and Remove carry the actions instead.

          Reported from a device — the tappable parts of setup do not read as
          tappable — and this card was the worst of them. The whole face is the
          target, and everything drawn on it was type or `hairline`, which
          measures **1.70:1** against the card. Nothing said "button" and
          nothing was above the WCAG 2.2 non-text floor.
        */}
        {material === null && <View testID="deck-open" style={styles.chevron} />}
      </Pressable>

      {material === null ? (
        <Text style={styles.accepts}>{accepts(limits)}</Text>
      ) : (
        <View style={styles.actions}>
          <View style={styles.hairline} />
          {/*
            Held, not hidden, while the deck is being read. Replace
            mid-extraction races the poll watching the old material, and two
            live controls under a spinner invite fixing something that is not
            broken. Disabled rather than absent because the card would jump
            when they returned — and a greyed control says they will.
          */}
          <View style={styles.acts}>
            <Act label="Replace" spoken="Replace this deck" onPress={onAttach} held={reading} />
            <Act label="Remove" spoken="Remove this deck" onPress={onRemove} held={reading} />
          </View>
        </View>
      )}
    </View>
  );
}

/** A page with two ruled lines on it. Drawn, because nothing here ships icons. */
function Mark({ tone }: { tone: 'empty' | 'held' | 'failed' }) {
  // `onSurfaceVariant` for the empty slot rather than `hairline`, which was
  // 1.70:1 against the card — a divider's ink, used to draw the icon for this
  // screen's second-largest action. Quieter than the held state's `primary`
  // and still a page somebody can see: 9.34:1.
  const ink =
    tone === 'failed'
      ? color.danger
      : tone === 'held'
        ? color.primary
        : color.onSurfaceVariant;

  return (
    <View style={[styles.page, { borderColor: ink }]}>
      <View style={[styles.rule, { backgroundColor: ink }]} />
      <View style={[styles.rule, styles.ruleShort, { backgroundColor: ink }]} />
    </View>
  );
}

/** One named action under an attached deck. Text, because the row is not a form. */
function Act({
  label,
  spoken,
  onPress,
  held = false,
}: {
  label: string;
  spoken: string;
  onPress: () => void;
  held?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={spoken}
      accessibilityState={{ disabled: held }}
      disabled={held}
      onPress={onPress}
      style={({ pressed }) => [styles.act, pressed && styles.pressed]}
    >
      <Text style={[styles.actLabel, held && styles.actHeld]}>{label}</Text>
    </Pressable>
  );
}

/**
 * What the deck row says about itself.
 *
 * The absent case is not an empty state to be apologised for — a deckless room
 * is first-class (`docs/auditor-grounding.md`), so the line says what attaching
 * one *buys* rather than what is missing.
 */
function says(material: AttachedMaterial | null): string {
  if (material === null) {
    return 'Optional. With one, they quote your own figures back at you.';
  }
  if (material.state === 'extracting') return 'Being read. This takes a moment.';
  if (material.state === 'failed') {
    return 'Could not be read. Attach another, or start without it.';
  }

  return 'Read, and ready to be used against you.';
}

/**
 * The constraints, said before the picker rather than after a refusal.
 *
 * The formats are named in words rather than as MIME types, and stated even
 * when the limits call failed, because they are a fact about the product.
 * Somebody holding a Keynote export needs to know before they go looking for
 * it — the picker filters, so otherwise they meet an empty folder and no
 * explanation.
 */
function accepts(limits: MaterialLimits | null): string {
  if (limits === null) return 'PDF or PowerPoint.';

  const mb = Math.round(limits.maxUploadBytes / (1024 * 1024));

  return `PDF or PowerPoint, up to ${mb} MB and ${limits.maxPagesPerMaterial} pages.`;
}

const PAGE_W = 26;
const PAGE_H = 32;

const styles = StyleSheet.create({
  card: {
    backgroundColor: color.card,
    borderRadius: radius.card,
    paddingHorizontal: space.base,
  },

  face: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.base,
    paddingVertical: space.base,
    minHeight: 44,
  },
  pressed: { opacity: 0.7 },

  said: { flex: 1, gap: space.hair },
  title: { ...type.labelLg, color: color.onSurface },
  detail: { ...type.bodySm, color: color.onSurfaceVariant },
  // Colour is not the only carrier — the sentence says it could not be read,
  // and the row announces itself. This is the third signal, not the first.
  wrong: { color: color.danger },

  /**
   * The constraints line, outside the pressable face.
   *
   * Inside it, it would be read aloud as part of the button's own label, which
   * makes the spoken name of the control a paragraph. It is context for the
   * decision, not part of the action.
   */
  accepts: {
    ...type.bodySm,
    color: color.onSurfaceVariant,
    // Aligned under the text rather than under the mark, so the face and this
    // read as one block with a hanging indent rather than two stacked lines.
    paddingLeft: PAGE_W + space.base,
    paddingBottom: space.base,
  },

  actions: { paddingBottom: space.tight },
  acts: { flexDirection: 'row' },
  act: {
    minHeight: 44,
    justifyContent: 'center',
    paddingRight: space.section,
  },
  actLabel: { ...type.labelLg, color: color.primary },
  actHeld: { color: color.onSurfaceVariant },

  // The drawn page. These are icon geometry rather than layout, which is why
  // they are numbers here and not tokens — same as the chevron in `SignInSheet`
  // and the marker in `Chair`.
  page: {
    width: PAGE_W,
    height: PAGE_H,
    borderWidth: 2,
    borderRadius: 4,
    paddingHorizontal: 5,
    justifyContent: 'center',
    gap: 4,
  },
  rule: { height: 2, borderRadius: 1 },
  ruleShort: { width: '60%' },

  /**
   * The affordance, drawn rather than shipped as an icon — the same two borders
   * on a rotated square that `AuthorRow` and `PanelSetup`'s rail end use, so
   * one shape means one thing across the screen.
   */
  chevron: {
    width: 10,
    height: 10,
    borderRightWidth: 2,
    borderTopWidth: 2,
    borderColor: color.onSurfaceVariant,
    transform: [{ rotate: '45deg' }],
    // The mass sits left of centre once rotated; this puts the point on the
    // row's right edge rather than the bounding box.
    marginRight: 3,
  },

  hairline: { height: 1, backgroundColor: color.hairline, opacity: 0.5 },
});
