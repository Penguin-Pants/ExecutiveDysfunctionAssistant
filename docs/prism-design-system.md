# PRISM — Jarrod Davis Personal Brand Design System BETA
Derived from the "Color Picker" card reference.

## 1. Dark Mode

Dark mode is the default and primary mode for PRISM. The system was built around a dark plum surface (`--plum-950`) as the identity anchor, light canvas is the supporting surface, not the reverse. Any implementation (site, deck, app) should default to dark mode on load.

### Mode strategy

| Mode | Canvas | Card surface | Behavior |
|---|---|---|---|
| **Dark (default)** | `--plum-950` | `--plum-900` (elevated) | Full-bleed dark background. Preview card becomes the "raised" surface, one step lighter than canvas, per the existing elevation pattern already defined for hover/nested states. |
| **Light (alt)** | `--canvas-100` | `--plum-950` | Current documented behavior: dark card floats on light canvas. |

### Token remapping for dark mode

Dark mode inverts which token plays "canvas" vs "card," it does not invert ink or accent tokens.

| Token | Light mode value | Dark mode value |
|---|---|---|
| `--canvas` (page bg) | `--canvas-100` (`#EEF0F4`) | `--plum-950` (`#1E1526`) |
| `--surface` (card bg) | `--plum-950` (`#1E1526`) | `--plum-900` (`#251A30`) |
| `--surface-border` | `--plum-800` (`#33253F`) | `--plum-800` (`#33253F`), unchanged |
| `--text-primary` | `--ink-900` (`#16151A`) | `--ink-inverse` (`#F5F3F7`) |
| `--text-secondary` | `--ink-600` (`#5B5763`) | `--ink-600` at `80%` opacity |
| Accent gradient | unchanged | unchanged |
| Palette dots | unchanged | unchanged |

Do not remap `--red-500`, `--blue-500`, `--green-500`, `--purple-500`, or the accent gradient stops between modes. Semantic and signature colors stay fixed so a screenshot of either mode is still recognizably PRISM.

### Rules

- Labels: in dark mode, labels sit on the dark canvas using `--ink-inverse` (not `--ink-900`, which would fail contrast).
- Shadow: dark-mode cards use a lighter, lower-opacity shadow or a subtle `1px` border instead of the light-mode drop shadow (`rgba` shadows barely register against a dark canvas). Suggested: `0 1px 0 rgba(255,255,255,0.04)` inset highlight + `1px solid var(--plum-800)` border.
- Contrast check: `--ink-inverse` on `--plum-950` and `--ink-inverse` on `--plum-900` both exceed WCAG AA. Re-verify `--ink-600 at 80%` against `--plum-900` if used for secondary text.
- Toggling: if a manual light/dark toggle exists, persist the user's choice; don't re-default to dark on every load if they've chosen light.

## 2. Concept

The reference card is a dark plum tile with a warm-to-cool gradient swatch and four flat color dots, labeled in bold black sans-serif below on a light canvas. That contrast, a saturated dark card floating on a near-white page, is the whole system. Every other component inherits this pattern: dark surface, vivid single accent or gradient, bold restrained label.

**Signature element:** the gradient swatch chip. It reappears everywhere a "live preview" or "current state" needs showing (color values, active theme, progress, status).

## 3. Color Tokens

### Surfaces
| Token | Hex | Use |
|---|---|---|
| `--canvas-100` | `#EEF0F4` | Page background |
| `--canvas-50` | `#F7F8FA` | Card background on light surfaces |
| `--plum-950` | `#1E1526` | Primary dark card surface |
| `--plum-900` | `#251A30` | Elevated dark surface (hover/nested) |
| `--plum-800` | `#33253F` | Border on dark surfaces |

### Ink
| Token | Hex | Use |
|---|---|---|
| `--ink-900` | `#16151A` | Primary text, headings, labels |
| `--ink-600` | `#5B5763` | Secondary text |
| `--ink-inverse` | `#F5F3F7` | Text on dark surfaces |

### Accent gradient (the swatch)
| Token | Hex | Stop |
|---|---|---|
| `--grad-1` | `#FF4D4D` | 0% |
| `--grad-2` | `#FF9D3D` | 35% |
| `--grad-3` | `#FFC93D` | 60% |
| `--grad-4` | `#B24DFF` | 100% |

`--accent-gradient: linear-gradient(135deg, var(--grad-1) 0%, var(--grad-2) 35%, var(--grad-3) 60%, var(--grad-4) 100%);`

### Palette dots (semantic + selectable colors)
| Token | Hex | Semantic use |
|---|---|---|
| `--red-500` | `#F0473E` | Danger / error |
| `--blue-500` | `#2D7DF6` | Info / primary action |
| `--green-500` | `#34C77B` | Success |
| `--purple-500` | `#A855F7` | Highlight / new |

## 4. Typography

### Font families

| Token | Family | Role |
|---|---|---|
| `--font-primary` | `IBM Plex Mono` | Display, labels, card titles, data/hex values |
| `--font-secondary` | `IBM Plex Sans` | Body copy, secondary/descriptive text |

```css
--font-primary: 'IBM Plex Mono', 'SF Mono', Menlo, monospace;
--font-secondary: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif;
```

IBM Plex Mono and IBM Plex Sans share the same type family lineage, so pairing them reads as intentional rather than mismatched. Mono is the system's primary voice, used for display and labels as well as data, which is a deliberate departure from systems that reserve mono for numbers only. This gives the brand a technical, distinctive signature.

- **Display / Labels:** `--font-primary` (IBM Plex Mono), weight 600–700, tight tracking (-0.01em). Used for card titles like "Color Picker." (Plex Mono's heaviest standard web weight is 700, so cap here rather than requesting 800.)
- **Body:** `--font-secondary` (IBM Plex Sans), weight 400–500, `--ink-600` for secondary copy.
- **Data / Mono:** `--font-primary` (IBM Plex Mono), for hex values and numeric readouts. Same family as display, so no separate mono token is needed.

Scale:
| Role | Size | Weight | Line height | Font |
|---|---|---|---|---|
| H1 | 32px | 700 | 1.15 | Primary (Mono) |
| H2 | 24px | 700 | 1.2 | Primary (Mono) |
| Label (card title) | 18px | 600 | 1.3 | Primary (Mono) |
| Body | 15px | 450 | 1.5 | Secondary (Sans) |
| Caption / mono | 13px | 500 | 1.4 | Primary (Mono) |

## 5. Shape & Spacing

- Card radius: `20px` (matches reference card corners)
- Inner chip radius: `10px` (matches swatch rectangle)
- Dot size: `16px` diameter, `8px` gap between dots
- Base spacing unit: `4px`. Card padding: `24px` (6 units).
- Shadow on dark card (resting on light canvas): `0 8px 24px rgba(30, 21, 38, 0.18)`

### Spacing scale

| Token | Value |
|---|---|
| `--space-1` | `4px` |
| `--space-2` | `8px` |
| `--space-4` | `16px` |
| `--space-6` | `24px` |
| `--space-8` | `32px` |

Use these five steps for all margin/padding/gap values. Don't introduce arbitrary pixel values outside this ladder.

## 6. Core Component: the Preview Card

Structure, top to bottom:
1. Dark surface container (`--plum-950`, `20px` radius, `24px` padding)
2. Centered preview chip (gradient or single-color swatch, `72×48px`, `10px` radius, subtle border `1px solid var(--plum-800)`)
3. Row of palette dots below chip, centered, `8px` gap
4. Label sits **outside and below** the dark card, on the canvas, bold and left-aligned

This separation (interactive/visual content inside the dark card, identity/label outside on canvas) is the system's core layout rule. Don't put labels inside the dark card; don't float dots or chips directly on canvas.

## 7. States

- **Selected dot:** `2px` ring, offset `2px`, ring color `--ink-inverse` on dark, `--ink-900` on light
- **Hover (card):** lift `2px`, shadow intensifies to `0 12px 32px rgba(30,21,38,0.24)`
- **Disabled:** `40%` opacity, no shadow

## 8. Component: Buttons

Shared shape across all variants: `--font-primary` (IBM Plex Mono), 14px, weight 600, `10px 20px` padding, `10px` radius (matches chip radius), no gradient on any variant.

| Variant | Background | Text | Border | Hover |
|---|---|---|---|---|
| Primary | `--plum-950` | `--ink-inverse` | none | bg → `--plum-900` |
| Accent | `--purple-500` | `--ink-inverse` | none | bg darkens ~10% |
| Ghost | transparent | `--ink-900` | `1px solid var(--plum-800)` | bg → `--canvas-50` |
| Disabled | `--plum-950` | `--ink-inverse` | none | n/a, `40%` opacity, `not-allowed` cursor |

**Gradient exclusion:** the accent gradient is reserved exclusively for the preview chip (Section 6). Buttons never use `--accent-gradient`, including CTA/hero buttons. Use `--purple-500` (solid) for the accent/CTA variant instead. This keeps the gradient a true signature moment rather than a repeated decorative pattern.

```css
.btn {
  font-family: var(--font-primary);
  font-size: 14px;
  font-weight: 600;
  padding: 10px 20px;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  transition: background .15s ease;
}
.btn-primary { background: var(--plum-950); color: var(--ink-inverse); }
.btn-primary:hover { background: var(--plum-900); }
.btn-accent { background: var(--purple-500); color: var(--ink-inverse); }
.btn-ghost { background: transparent; color: var(--ink-900); border: 1px solid var(--plum-800); }
.btn-disabled { background: var(--plum-950); color: var(--ink-inverse); opacity: .4; cursor: not-allowed; }
```

## 9. Usage Rules

- Never place more than one gradient swatch per card, it's the signature, not a pattern to repeat densely.
- Dots are always flat, no gradients on dots, gradients are reserved for the "current value" chip.
- Buttons never use the accent gradient, not even hero/CTA buttons. Use solid `--purple-500` for accent buttons instead.
- Labels are always bold and sit on canvas, never inside the plum card.
- Minimum contrast: `--ink-900` on `--canvas-100` and `--ink-inverse` on `--plum-950` both exceed WCAG AA.
