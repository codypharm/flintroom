---
name: Kinetic Clarity
colors:
  surface: '#fdf9f6'
  surface-dim: '#ddd9d6'
  surface-bright: '#fdf9f6'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f7f3f0'
  surface-container: '#FFFFFF'
  surface-container-high: '#ebe7e5'
  surface-container-highest: '#e5e2df'
  on-surface: '#1c1b1a'
  on-surface-variant: '#5a4138'
  inverse-surface: '#31302f'
  inverse-on-surface: '#f4f0ed'
  outline: '#8f7066'
  outline-variant: '#e3bfb2'
  surface-tint: '#a83900'
  primary: '#a43700'
  on-primary: '#ffffff'
  primary-container: '#cd4700'
  on-primary-container: '#fffbff'
  inverse-primary: '#ffb59a'
  secondary: '#5f5e5e'
  on-secondary: '#ffffff'
  secondary-container: '#e2dfde'
  on-secondary-container: '#636262'
  tertiary: '#71564c'
  on-tertiary: '#ffffff'
  tertiary-container: '#8b6e64'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffdbcf'
  primary-fixed-dim: '#ffb59a'
  on-primary-fixed: '#380d00'
  on-primary-fixed-variant: '#802a00'
  secondary-fixed: '#e5e2e1'
  secondary-fixed-dim: '#c8c6c5'
  on-secondary-fixed: '#1c1b1b'
  on-secondary-fixed-variant: '#474746'
  tertiary-fixed: '#ffdbcf'
  tertiary-fixed-dim: '#e2bfb3'
  on-tertiary-fixed: '#2a170f'
  on-tertiary-fixed-variant: '#5a4138'
  background: '#fdf9f6'
  on-background: '#1c1b1a'
  surface-variant: '#e5e2df'
  outline-soft: '#E3BFB2'
  accent-warm: '#FFB59A'
typography:
  display-lg:
    fontFamily: Hanken Grotesk
    fontSize: 64px
    fontWeight: '800'
    lineHeight: 72px
    letterSpacing: -0.03em
  headline-lg:
    fontFamily: Hanken Grotesk
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
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
  label-lg:
    fontFamily: Hanken Grotesk
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: Hanken Grotesk
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  headline-lg-mobile:
    fontFamily: Hanken Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  margin-desktop: 80px
  gutter-desktop: 32px
  max-width: 1280px
  unit-xs: 4px
  unit-sm: 8px
  unit-md: 16px
  unit-lg: 24px
  unit-xl: 48px
  unit-xxl: 80px
---

## Brand & Style

The design system embodies a "Kinetic Clarity" aesthetic—a sophisticated blend of high-energy tech-forwardness and professional restraint. It is designed specifically for a desktop experience where information density must be balanced with visual breathing room to maintain focus and authority.

The visual style is **Minimalist / Corporate Modern**, leaning into precision and high-fidelity execution. It utilizes a refined color palette and precise geometry to evoke feelings of innovation, reliability, and momentum. The interface should feel "expensive" yet accessible, prioritizing clarity of thought and ease of navigation through generous whitespace and a strict mathematical grid.

**Target Audience:** High-stakes professionals, startup founders, and enterprise teams who require a polished, distraction-free environment to execute complex tasks.

## Colors

The color strategy focuses on high-contrast "moments" against a serene, neutral canvas. 

- **Primary (#E65100):** A bold, burnt orange used exclusively for primary calls to action, active states, and brand signatures. It provides the "kinetic" spark within the design.
- **Secondary (#1A1A1A):** A deep, ink-black for high-contrast typography and structural elements, ensuring a grounded and professional feel.
- **Surface & Neutrals:** The foundation is a soft off-white (#FDF9F6), which reduces the harshness of pure white while maintaining a clean, minimalist aesthetic. Pure white (#FFFFFF) is reserved for cards and elevated containers to create a subtle layered effect.
- **Accents:** Muted terracotta and warm peach tones are used for secondary UI elements like outlines and surface tints to keep the palette cohesive and warm.

## Typography

This system utilizes **Hanken Grotesk** exclusively to maintain a sharp, geometric, and modern identity. 

The type hierarchy is designed for a "scan-first" desktop experience. Display and Large Headlines use heavy weights (700-800) and negative letter spacing to create a powerful visual impact. Body text is optimized for long-form legibility with generous line heights (1.5x - 1.6x) and a comfortable 18px base for primary information. Labels use slightly increased letter spacing and a semi-bold weight to ensure clarity in navigation and small-scale UI components.

## Layout & Spacing

The layout is built on a **Fixed Grid** system for the desktop landing page to ensure a premium, curated experience regardless of monitor size.

- **Grid:** A 12-column grid with a 1280px max-width, featuring 32px gutters and 80px side margins for a spacious, "editorial" feel.
- **Rhythm:** An 8px linear scale is used for all internal component spacing, while 24px (unit-lg) is the standard for card padding and section gaps. 
- **Adaptation:** On tablet, margins shrink to 40px with 24px gutters. On mobile, the grid collapses to a single column with 20px margins, and vertical spacing between sections is reduced by 40% to maintain momentum.

## Elevation & Depth

This design system uses **Tonal Layers** combined with **Ambient Shadows** to create a refined sense of depth without clutter.

- **Layer 0 (Base):** The #FDF9F6 surface.
- **Layer 1 (Cards):** Pure white surfaces with a soft, multi-layered shadow. The shadow should feel like a natural light source from above: `0px 4px 20px rgba(26, 26, 26, 0.04)`.
- **Layer 2 (Overlays):** Modals and dropdowns use a deeper shadow to pull them closer to the user: `0px 12px 40px rgba(26, 26, 26, 0.08)`.
- **Layer 3 (Primary Focus):** Primary buttons use a subtle color-tinted shadow (Primary Orange at 20% opacity) to create a "glow" effect, emphasizing their importance.

## Shapes

The shape language is consistently **Rounded**, striking a balance between approachable softness and professional structure. 

Standard containers and cards utilize a 0.5rem (8px) radius as a base, scaling up to 1rem (16px) for large hero sections or feature blocks. Buttons and input fields follow a "Semi-Pill" aesthetic—highly rounded but not necessarily full pills—to maintain a modern, tech-forward silhouette. This geometry softens the high-contrast typography and keeps the "minimalist" style from feeling cold or sharp.

## Components

### Buttons
- **Primary:** Burnt Orange background, White text. Semi-pill shape. Subtle 2px lift on hover with a Primary-tinted shadow.
- **Secondary:** White background, 1.5px Secondary (#1A1A1A) border, Secondary text. High-fidelity hover transition to a faint grey background.
- **Ghost:** No background or border. Text-only with Primary Orange used for the hover state.

### Cards
- Pure White background with Layer 1 shadows. 
- No borders. 
- Padding: 32px internal (unit-xl) to emphasize whitespace and premium quality.

### Input Fields
- Soft Grey (#E5E2E1) subtle border.
- 16px internal padding.
- Focus State: 2px Primary Orange border with a 4px soft orange outer glow.

### Chips & Lists
- **Chips:** Small 4px radius, light tint of Primary (#FFDBCC) with high-contrast text.
- **Lists:** Desktop lists should be borderless, using 16px of vertical spacing between items. Active items are highlighted with a vertical 4px bar of Primary Orange on the left edge.

### Navigation
- Desktop header: 80px height, semi-transparent background with a heavy backdrop blur (Glassmorphism effect) to maintain depth while scrolling.