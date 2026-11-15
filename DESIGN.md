---
name: RELOOP AI
description: Municipal Bin Stencils. Every item has a coloured, stencilled lane.
colors:
  paper: "#ffffff"
  surface: "#f2f4f1"
  surface-2: "#e6eae4"
  line: "#d5dbd3"
  ink: "#14211a"
  ink-soft: "#4d5a52"
  wet: "#1f6b3a"
  wet-deep: "#164f2b"
  dry: "#1d5fa8"
  reuse: "#a9500c"
  textile: "#7a3e8f"
  ewaste: "#3f4a54"
  hazard: "#b42318"
  medical: "#e2b007"
  unsure: "#646d67"
typography:
  hero:
    fontFamily: "Big Shoulders Stencil, Arial Narrow, sans-serif"
    fontSize: "clamp(3rem, 9.2vw, 6rem)"
    fontWeight: 800
    lineHeight: 0.9
    letterSpacing: "0"
  display:
    fontFamily: "Big Shoulders Stencil, Arial Narrow, sans-serif"
    fontSize: "clamp(2.5rem, 6vw, 4.25rem)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Big Shoulders Stencil, Arial Narrow, sans-serif"
    fontSize: "clamp(2rem, 4.2vw, 3rem)"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "0.01em"
  title:
    fontFamily: "Mukta, system-ui, Segoe UI, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "Mukta, system-ui, Segoe UI, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "Mukta, system-ui, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "0.02em"
rounded:
  s: "6px"
  m: "12px"
  l: "20px"
  pill: "999px"
spacing:
  "1": "0.25rem"
  "2": "0.5rem"
  "3": "0.75rem"
  "4": "1rem"
  "5": "1.5rem"
  "6": "2rem"
  "7": "3rem"
  "8": "4.5rem"
  "9": "6rem"
components:
  button-primary:
    backgroundColor: "{colors.wet}"
    textColor: "{colors.paper}"
    typography: "{typography.title}"
    rounded: "{rounded.pill}"
    padding: "0 1.5rem"
    height: "48px"
  button-primary-hover:
    backgroundColor: "{colors.wet-deep}"
  button-quiet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 1.5rem"
    height: "48px"
  tag:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink-soft}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.1em 0.55em"
  chute-slot:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.m}"
    padding: "1rem 1.5rem"
  chute-slot-filled:
    backgroundColor: "{colors.wet}"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.l}"
    padding: "1.5rem"
  chit:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.m}"
    padding: "1.5rem"
  hazard-strip:
    backgroundColor: "{colors.hazard}"
    textColor: "{colors.paper}"
    padding: "1rem 0"
---

# Design System: RELOOP AI

## Overview

**Creative North Star: "Municipal Bin Stencils"**

The interface is the segregation system itself. Every item belongs in a coloured, stencilled lane, and the product shows those lanes as moulded-plastic bins: flat colour fields with a darker lid band across a rounded top, stencilled uppercase names, painted dashed lines as route markers. The ground is plain white with soft green-grey surfaces, so the eight municipal colours are the only loud things on a page and each one means a destination.

Density is calm and practical, sized for a household member on a low-end Android phone on mobile data: large tap targets (48px buttons, 44px menu control), one body face, self-hosted fonts, every graphic an inline SVG. Motion is limited to one press-down on lanes and buttons and short colour transitions; nothing animates on load or on scroll.

Honesty is a visual material here. Certainty is drawn as a shape, demo content is labelled in place, listing statuses are stamped on, and the red hazard strip sits at the foot of every page.

**Key Characteristics:**
- White ground, ink text, soft neutral surfaces; forest green (the wet-waste lane) doubles as the brand accent.
- Eight lane colours taken from municipal bins, each carrying text that passes WCAG AA.
- Big Shoulders Stencil, uppercase, weight 800, for headlines, lane names, step numbers, stamps and the wordmark; Mukta for everything else.
- Bin silhouette: bigger radius on top corners than bottom, with a darker lid band.
- Flat by default; one soft lift shadow for paper chits and the open mobile menu.

## Colors

A white-and-ink civic palette in which colour is reserved for lanes, and every lane colour is a destination.

### Primary
- **Wet-Bin Forest Green** (`wet`): the wet-waste lane and the brand accent. Primary buttons, links, the filled chute, step numbers, certainty marks, active nav underline, the mark's tile, text selection, `accent-color` and caret.
- **Deep Forest** (`wet-deep`): hover state for primary buttons and links; text on the pale green notice.

### Lane colours (municipal bin colours)
Each lane colour is a fill with its own text colour, and every pairing passed WCAG AA in the shipped build.
- **Dry-Bin Blue** (`dry`): dry recyclables; also the Reserved stamp. White text.
- **Reuse Orange** (`reuse`): reusable/donatable; also the Pending stamp. White text.
- **Textile Plum** (`textile`): textiles. White text.
- **E-Waste Slate** (`ewaste`): e-waste. White text.
- **Hazard Red** (`hazard`): household hazardous; the hazard strip, the hazard tag and the Rejected stamp. White text.
- **Biomedical Yellow** (`medical`): sanitary and biomedical. Ink text, never white.
- **Unsure Grey** (`unsure`): other/uncertain. White text.

### Neutral
- **Paper White** (`paper`): page ground, chits, quiet buttons.
- **Soft Sage Surface** (`surface`): the chute tray, alternating sections (how it works, donations), panels, nav hover.
- **Sage Tint** (`surface-2`): tag backgrounds, mobile menu row dividers.
- **Hairline** (`line`): header and page-head borders, guide row rules, quiet button and account pill borders.
- **Bin Ink** (`ink`): body text, the chute slot, the footer ground, heavy 2px section rules, focus outline.
- **Soft Ink** (`ink-soft`): ledes, secondary copy, field labels, the Completed stamp.

### Named Rules
**The Lane Means Destination Rule.** A lane colour is used only for its waste stream (a bin, a guide row, a page bin) or a status that borrows its meaning (stamps). Never as decoration, a section tint or a gradient.

**The Lane Ink Rule.** Every lane fill pairs with white text, except Biomedical Yellow, which pairs with ink. A new lane or status colour ships only with a text pairing that passes WCAG AA.

**The One Green Rule.** Forest green is both the wet lane and the brand accent; no second accent colour exists. Interactive emphasis is green or ink.

## Typography

**Display Font:** Big Shoulders Stencil, variable 100–900, self-hosted (with Arial Narrow, sans-serif). Logo and bin labels only.
**Body and Heading Font:** Mukta 400/500/700, self-hosted (with system-ui, Segoe UI, sans-serif)

**Character:** Warm, highly legible Indic-friendly sans for everything people read; the condensed municipal stencil survives only where it is painted on a bin (lane names) and in the wordmark.

### Hierarchy
- **Hero** (Mukta 700, clamp(2.25rem, 6.5vw, 4.25rem), 1.08, sentence case): the homepage headline only.
- **Display** (Mukta 700, clamp(2rem, 5vw, 3.25rem), 1.1): page titles, the "why" statement.
- **Headline** (Mukta 700, clamp(1.625rem, 3.5vw, 2.25rem), 1.15): section headings.
- **Display-3** (Mukta 700, 1.375rem, 1.25): panel headings.
- **Title** (Mukta 700, 1.1875rem, 1.3): h3 inside rows, steps, chits; also the button face at 1.0625rem.
- **Body** (Mukta 400, 1.0625rem, 1.6): running text. Ledes 1.1875rem in soft ink, capped at 40–42rem.
- **Label** (Mukta 700, 0.75rem, 0.02em): tags. Footer column headings use Mukta 700 0.875rem in sentence case.
- **Bin label** (Big Shoulders Stencil 800, uppercase): lane names on bins and chips, the page bin, the result bin, the wordmark.

### Named Rules
**The Stencil Is For Bins Rule.** The stencil face sets only lane names on bins and chips and the wordmark, always uppercase and weight 800. Headings, numbers, stamps, form labels and body copy use Mukta in sentence case. (Changed 2026-11-15: the stencil headings were hard to read.)

**The Sentence-Case Small Type Rule.** Small Mukta labels stay sentence case. No uppercase tracked micro-labels above headings.

## Layout

A single centred column, max 76rem, with a 16px gutter on phones and 32px from 48em. Breakpoints are 30em (phone compactions), 48em (two- and three-column grids, the chute's side actions) and 62em (desktop nav, eight lanes in one row, three-column guide rows). Spacing runs a nine-step scale from 0.25rem to 6rem; sections use clamp(3rem, 8vw, 6rem) block padding, and alternate between white and the sage surface rather than using boxes. The homepage's eight lanes are a 4×2 grid on phones and 8×1 on desktop, kept inside the first phone viewport by hiding lane gists and the chute icon below 30em. Lists are separated by rules (2px ink at the top, 1px hairline between rows), not cards.

## Elevation & Depth

Flat by default. Depth comes from tonal surfaces (white on sage) and from inset "lid" bands that give bins their moulded top. One soft ambient shadow exists, used only where a paper object sits on a surface.

### Shadow Vocabulary
- **Lift** (`box-shadow: 0 1px 2px rgb(20 33 26 / 0.06), 0 6px 18px -6px rgb(20 33 26 / 0.14)`): donation chits on the sage section; the open mobile menu sheet.
- **Bin lid** (`box-shadow: inset 0 0.5rem 0 rgb(0 0 0 / 0.2)`, 0.625rem on the page bin): guide bins and page-head bins. The homepage lanes draw the same lid as an absolutely positioned band (rgb(0 0 0 / 0.22), darkening to 0.32 on hover).

### Named Rules
**The Paper Only Lifts Rule.** Only paper-like objects (chits, the menu sheet) take the lift shadow. Panels, buttons and bins never take a drop shadow.

## Shapes

Rounded but not soft. Three radii: 6px for small marks (stamps, focus outline, nav hover), 12px for bins, chits and the chute slot, 20px for panels and the chute tray; pills (999px) for every button, tag, file button and the account link. The signature silhouette is the bin: larger radius on the top corners than the bottom (12px/6px for lanes and page bins, 20px/12px for the chute tray, 6px/4px for guide bins). Lines are painted: route connectors are 4px dashed stripes (14px on, 12px off) in ink at 25% opacity; chits carry a scalloped tear edge along the top. The mark is a white stencil-bridged ring on a 8px-rounded green tile.

## Components

### Buttons
Tactile, plain pills.
- **Shape:** full pill (999px), 48px min height, 2px border.
- **Primary:** forest green with white Mukta 700 text, trailing arrow icon.
- **Quiet:** paper with ink text and hairline border; border turns ink on hover.
- **Hover / Active:** 120ms colour transition; press moves down 1px. Disabled at 50% opacity.
- On phones the quiet chute action collapses to an underlined text link.

### Tags
- **Style:** pill, sage tint ground, soft ink Mukta 700 0.75rem. The hazard variant uses pale red (#fbe9e7) with hazard red text and an alert icon. "Demo" tags mark demonstration data in place.

### Cards / Containers
- **Panel:** 20px radius, sage surface, 1.5rem padding, flat. "Coming soon" panels are white with a 2px hairline border.
- **Chit:** donation listing as a paper slip: white, 12px radius, lift shadow, scalloped top edge, dashed rule above a two-column field list.

### Inputs / Fields
- **The chute:** the one upload control. The whole ink slot is the label for the file input, with a camera badge, a bold prompt and a hint; the native file button is a white pill. Focus draws a 3px green outline around the slot.
- **Filled state:** when a photo is chosen, CSS `:has(:valid)` turns the slot forest green, swaps the prompt to "Photo ready" and the camera for a check. No JavaScript.

### Navigation
- **Desktop (62em+):** Mukta 500 ink links in a row, sage hover, active page marked by a 3px green bottom inset; Admin in soft ink; account as a hairline-bordered pill.
- **Mobile:** a native `<details>` pill labelled Menu with a menu/close icon, opening a full-width paper sheet with the lift shadow and 1.125rem links divided by sage rules; the active link turns green and bold.
- **Footer:** ink ground, white links, muted sage column headings, light green "AI" in the wordmark.

### Lanes (signature)
Eight bin-shaped links in lane colours, a darker lid band across the top, a stencilled lane name and a one-line gist. The only motion in the system: pressing a lane drops it 3px (90ms). The same bin appears small in guide rows and as the page bin beside each feature page title, so every page announces its lane.

### Certainty marks
Three 18px green icons: filled circle (Clear), half-filled (Likely), hollow (Unsure, so we ask). Always paired with the word.

### Stamps
Listing status as a rubber stamp: Mukta 700 in sentence case, 2.5px current-colour border, 6px radius, rotated −6°. Available green, Reserved blue, Pending orange, Completed soft ink, Rejected red.

### Hazard strip
Full-width hazard red band between main and footer, white text with an alert icon and a bold white link. Identical on every page.

### Icons
One family drawn on a 24px grid: 1.75 stroke, round caps and joins, `currentColor`, inline SVG, decorative and hidden from assistive tech unless labelled.

## Do's and Don'ts

### Do:
- **Do** use a lane colour only for its waste stream, with its tested text colour: white on all lanes, ink on Biomedical Yellow.
- **Do** show AI certainty with the filled / half / hollow marks plus a word, never a percentage.
- **Do** keep the red hazard strip identical on every page, between main content and footer.
- **Do** show listing statuses as rotated stamps that stay visible; a rejected or completed listing keeps its stamp.
- **Do** build Operate pages (scanner, assistant, donate, explore, centres, dashboards) inside the shared shell: header, page head with lane bin, hazard strip, footer.
- **Do** use the bin silhouette (larger top radius, lid band) for anything that represents a lane.
- **Do** label demonstration data in place with a "Demo" tag or demo note.
- **Do** keep motion to colour transitions of 160ms or less and the single press-down; respect reduced motion.
- **Do** keep tap targets at 44px or more and the focus outline at 3px (ink on light, white on red and ink grounds).

### Don't:
- **Don't** show certainty as a percentage, score or progress bar.
- **Don't** introduce a second accent colour or use lane colours as decorative tints or gradients.
- **Don't** put white text on Biomedical Yellow.
- **Don't** use the stencil face for headings, numbers, statuses, body copy or form labels. It is for bin labels and the wordmark only.
- **Don't** add uppercase tracked eyebrow labels above headings.
- **Don't** add drop shadows to panels, buttons or bins; only paper objects lift (the inset bin lid is not a drop shadow).
- **Don't** animate on load or scroll, or add motion beyond press feedback.
- **Don't** ship raster icons or icon fonts; icons are inline SVG from the one family.
