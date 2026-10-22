# Design token register

Tokens live in `src/homefile/web/static/tokens.css`. This register records the
measured WCAG 2.2 contrast for every text/background pair the components use.
Ratios were computed from sRGB relative luminance with the WCAG formula; a
component may only use a pair listed here.

- Light theme is the default; dark theme follows `prefers-color-scheme: dark`.
- Text target: 4.5:1. Essential UI indicators (input and control borders,
  focus ring): 3:1.
- `--color-border` is decorative separation only and is not used as the sole
  indicator of a control boundary.

## Light theme

| Foreground | Background | Ratio | Use |
|---|---|---|---|
| `--color-ink` `#20221f` | `--color-canvas` `#f5f3ee` | 14.46:1 | Body text |
| `--color-ink` `#20221f` | `--color-surface` `#fffdf8` | 15.77:1 | Panels, tables |
| `--color-ink-muted` `#5f645c` | `--color-canvas` `#f5f3ee` | 5.47:1 | Secondary text |
| `--color-ink-muted` `#5f645c` | `--color-surface` `#fffdf8` | 5.96:1 | Hints, panel notes |
| `--color-accent` `#b6422b` | `--color-canvas` `#f5f3ee` | 4.98:1 | Links |
| `--color-accent` `#b6422b` | `--color-surface` `#fffdf8` | 5.43:1 | Links in panels |
| `--color-accent-ink` `#fffaf2` | `--color-accent` `#b6422b` | 5.31:1 | Primary button label |
| `--color-success` `#2f6045` | `--color-success-surface` `#e7efe6` | 6.21:1 | Confirmed badge, local mode |
| `--color-warning` `#7d5713` | `--color-warning-surface` `#f7eed8` | 5.60:1 | Needs-review badge |
| `--color-danger` `#9a2a2a` | `--color-danger-surface` `#f8e5e2` | 6.32:1 | Error and destructive badge |
| `--color-border-strong` `#83867d` | `--color-surface` `#fffdf8` | 3.64:1 | Input and control border |
| `--color-focus` `#1f5f9e` | `--color-surface` `#fffdf8` | 6.48:1 | Focus ring |

## Dark theme

| Foreground | Background | Ratio | Use |
|---|---|---|---|
| `--color-ink` `#ecebe6` | `--color-canvas` `#17181a` | 14.88:1 | Body text |
| `--color-ink` `#ecebe6` | `--color-surface` `#1e2022` | 13.69:1 | Panels, tables |
| `--color-ink-muted` `#a8aca4` | `--color-canvas` `#17181a` | 7.70:1 | Secondary text |
| `--color-ink-muted` `#a8aca4` | `--color-surface` `#1e2022` | 7.08:1 | Hints, panel notes |
| `--color-accent` `#e2795c` | `--color-surface` `#1e2022` | 5.54:1 | Links |
| `--color-accent-ink` `#1a1210` | `--color-accent` `#e2795c` | 6.26:1 | Primary button label |
| `--color-success` `#8fc3a5` | `--color-success-surface` `#1f2c25` | 7.28:1 | Confirmed badge, local mode |
| `--color-warning` `#e0b168` | `--color-warning-surface` `#2c2519` | 7.69:1 | Needs-review badge |
| `--color-danger` `#e79289` | `--color-danger-surface` `#2e1d1b` | 6.78:1 | Error and destructive badge |
| `--color-border-strong` `#70757b` | `--color-surface` `#1e2022` | 3.52:1 | Input and control border |
| `--color-focus` `#7fb2e8` | `--color-surface` `#1e2022` | 7.34:1 | Focus ring |

## Status is never colour alone

Every status badge carries text plus a dot glyph (`::before`), so the label is
readable without colour. Error and success banners include a textual prefix
(`v` or `!`) and are announced with `role="status"` or `role="alert"`.

## Type and motion

| Token | Value | Use |
|---|---|---|
| `--font-body` | platform UI sans | Body and controls |
| `--font-display` | Georgia, Times New Roman, serif | Headings |
| `--font-mono` | Cascadia Mono, SFMono-Regular, Consolas | Hashes, paths, offsets |
| `--text-xs` … `--text-3xl` | 0.75rem … 2.25rem | Fixed scale, no viewport sizing |
| `--motion-fast` | 120ms | Control feedback |
| `--motion-standard` | 200ms | Panel transitions |
| `--motion-*` under `prefers-reduced-motion` | 0ms | Removes transitions |

## Re-measurement

Change a token here and in `tokens.css` together. To re-check a pair:

```python
def relative_luminance(hex_color: str) -> float:
    rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

def ratio(a: str, b: str) -> float:
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)
```
