---
name: PitchGo Design System
colors:
  surface: '#fcf9f8'
  surface-dim: '#dcd9d9'
  surface-bright: '#fcf9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f2'
  surface-container: '#f0eded'
  surface-container-high: '#eae7e7'
  surface-container-highest: '#e5e2e1'
  on-surface: '#1c1b1b'
  on-surface-variant: '#5a4138'
  inverse-surface: '#313030'
  inverse-on-surface: '#f3f0ef'
  outline: '#8f7066'
  outline-variant: '#e3bfb2'
  surface-tint: '#a83900'
  primary: '#a43700'
  on-primary: '#ffffff'
  primary-container: '#cd4700'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb59a'
  secondary: '#605e5c'
  on-secondary: '#ffffff'
  secondary-container: '#e5e2df'
  on-secondary-container: '#666462'
  tertiary: '#5a5c5c'
  on-tertiary: '#ffffff'
  tertiary-container: '#737575'
  on-tertiary-container: '#fcfcfc'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdbcf'
  primary-fixed-dim: '#ffb59a'
  on-primary-fixed: '#380d00'
  on-primary-fixed-variant: '#802a00'
  secondary-fixed: '#e5e2df'
  secondary-fixed-dim: '#c9c6c3'
  on-secondary-fixed: '#1c1b1a'
  on-secondary-fixed-variant: '#484745'
  tertiary-fixed: '#e2e2e2'
  tertiary-fixed-dim: '#c6c6c7'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#454747'
  background: '#fcf9f8'
  on-background: '#1c1b1b'
  surface-variant: '#e5e2e1'
  interrogation-ground: '#15110f'
  interrogation-tray: '#413c3a'
  interrogation-tray-lit: '#675f5b'
typography:
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Hanken Grotesk
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Hanken Grotesk
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Hanken Grotesk
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-md:
    fontFamily: Hanken Grotesk
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 36px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  container-padding: 20px
  gutter: 16px
---

## Brand & Style

This design system is built on a "Warm Professionalism" aesthetic. It balances the urgency of a high-growth startup environment with the approachability of a premium consumer app. The visual narrative focuses on clarity, airiness, and a "paper-on-surface" tactile feel.

The style leverages **Modern Minimalism** with a **Tactile** twist. By combining heavy white space, oversized radius corners, and subtle depth, the UI feels organic and trustworthy. It avoids the coldness of traditional corporate SaaS by utilizing a soft, warm background and vibrant, high-energy accents.

**Target Audience:** Entrepreneurs, sales professionals, and creators who need a fast, high-quality, and motivating platform to refine their message.

## Colors

The palette is designed to reduce eye strain while maintaining clear visual hierarchies.

- **Primary (#E65100):** A vibrant burnt orange used for critical actions, progress indicators, and brand-defining elements. It evokes energy and success.
- **Surface Background (#FDF9F6):** A soft, warm off-white that acts as the canvas. This creates a gentle contrast with container cards.
- **Surface Container (#FFFFFF):** Pure white used for cards and interactive inputs to provide a clean, elevated look.
- **On-Surface High Emphasis (#1A1A1A):** Dark charcoal for headers and primary titles to ensure maximum readability and a professional tone.
- **On-Surface Medium Emphasis (#757575):** A medium warm grey for body text, descriptions, and labels to create a natural hierarchy.

### The interrogation, and only the interrogation

Every surface in this system sits on the warm off-white. The live interrogation
does not, and it is the single exception: the phone lies flat on a desk for
twelve minutes while somebody argues, and a page-bright screen in that position
is a lamp pointed at the ceiling. Setup, debrief and sparring stay light. You go
into the dark room, and you come out.

The three values below are **derived from the committed primary, not chosen.**
`#a43700` is hue 20°; each holds that hue and moves only saturation and
lightness, so the dark surface is a deeper reading of the same identity rather
than a second palette that happens to live in the same app.

- **Interrogation Ground (#15110f)** — `hsl(20, 18%, 7%)`. Near-black that is
  unmistakably warm once it fills a screen: a darkroom under a safelight, not an
  OLED void. `inverse-surface` (#313030) is deliberately *not* used here — it is
  a near-neutral mid grey meant for snackbars, and bled across a whole screen it
  reads as a generic dark-mode app.
- **Interrogation Tray (#413c3a)** — `hsl(20, 6%, 24%)`. A quiet archetype: a
  seat that is occupied and not speaking.
- **Interrogation Tray Lit (#675f5b)** — `hsl(20, 6%, 38%)`. The archetype
  holding the floor, at exactly **3:1** against the ground — the WCAG 2.2
  non-text contrast floor, solved for rather than eyeballed.

Text on this ground uses the inverse tokens already in the palette:
`inverse-on-surface` (#f3f0ef) for the line, at 16.5:1, and `inverse-primary`
(#ffb59a) for anything active, at 11:1. Both are the existing light-on-dark
answers this system already had; nothing new was invented for them.

**Who is speaking is carried in text, not only in a tray.** Caption standards
require speaker identification wherever more than one person speaks, and a
tray deepening in peripheral vision tells a deaf or hard-of-hearing reader
nothing about which archetype is asking. The trays are reinforcement; the name
beside the line is the answer.

## Typography

This design system utilizes **Hanken Grotesk** for its crisp, geometric modernism and exceptional legibility at all scales.

The typographic scale emphasizes a strong vertical rhythm. Headlines use a tighter letter spacing and heavier weights to command attention, while body text remains airy with generous line heights to facilitate long-form reading of pitch decks or AI-generated scripts. 

For mobile-specific views, the primary headline scales down slightly to maintain optimal line wrapping on smaller screens.

## Layout & Spacing

The layout philosophy follows a **Fluid Content** model with a "safe margin" approach. 

- **Mobile:** A single-column layout with 20px horizontal margins. Elements use a 16px vertical rhythm.
- **Desktop/Tablet:** A 12-column grid with 24px gutters. Content is typically contained in a max-width of 1200px centered on the screen.

The spacing rhythm is strictly based on a 4px baseline, ensuring that every element—from the height of a button to the padding of a card—is a multiple of 4. This creates a subconscious sense of order and alignment. Use "lg" (24px) for most card internal paddings to maintain the spacious, modern feel.

## Elevation & Depth

Hierarchy is established through **Ambient Shadows** and tonal layering. The design avoids harsh borders, preferring to let depth define boundaries.

- **Level 0 (Background):** The soft off-white surface (#FDF9F6).
- **Level 1 (Cards/Containers):** Pure white surfaces (#FFFFFF) with a very soft, diffused drop shadow. Shadow specs: `X: 0, Y: 8, Blur: 24, Spread: -4, Color: rgba(26, 26, 26, 0.04)`.
- **Level 2 (Interactive/Floating):** Higher elevation for floating action buttons or active state items. Shadow specs: `X: 0, Y: 12, Blur: 32, Spread: -8, Color: rgba(26, 26, 26, 0.08)`.

This creates a "paper-like" stack where the content feels light and physically present.

## Shapes

The shape language is defined by extreme roundedness to convey friendliness and modern fluid design.

- **Containers & Cards:** Utilize a 28px corner radius. This creates a friendly "pod" look that softens the interface.
- **Buttons & Inputs:** Follow a pill-shaped (fully rounded) geometry. This makes touch targets feel more inviting and clearly distinguishes interactive elements from static content cards.
- **Icon Enclosures:** Small circular backgrounds for utility icons should maintain consistent padding to reflect the pill-shaped theme.

## Components

### Buttons
- **Primary:** Pill-shaped, Primary Orange background, White text. Bold weight.
- **Secondary:** Pill-shaped, Pure White background, Primary Orange or Neutral Dark border (1px), Neutral Dark text.
- **Size:** Large buttons should have a minimum height of 56px for mobile accessibility.

### Cards
- Pure White background with the Level 1 shadow. 
- Internal padding should be 24px.
- Use the 28px corner radius.

### Input Fields
- Pill-shaped with a 1px soft grey border or a slightly tinted background.
- Floating labels or clear placeholders in Medium Warm Grey.
- Focus state: Border transitions to Primary Orange with a subtle outer glow.

### Chips & Tags
- Used for categories or status. 
- Small pill-shaped containers with low-opacity Primary Orange backgrounds and high-opacity text.

### Lists
- Items are separated by generous whitespace rather than lines.
- Each list item should feel like its own "mini-card" or be grouped within a larger rounded container.