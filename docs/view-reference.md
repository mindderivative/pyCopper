# View file reference

A pyCopper interface is a YAML document. This is the complete vocabulary: every
node field, every widget, every style property.

For *why* it is shaped this way, see [ARCHITECTURE.md](../ARCHITECTURE.md).
This page is the what.

---

## Document shape

```yaml
root:                       # the widget tree
  name: root
  widget: Column
  children: [ ... ]

overlays:                   # optional: content that floats above the tree
  - name: confirm
    widget: Dialog
    open: "{{ confirming.get() }}"
```

A file containing a bare widget (no `root:`) is treated as the root, so the
smallest valid view is:

```yaml
widget: Text
text: Hello
```

---

## Node fields

Every node accepts these. Only `widget` is required.

| Field | Type | Meaning |
|---|---|---|
| `widget` | enum | Which widget. An unknown name fails at load. |
| `name` | string | Optional, **unique** handle. Used by `find()`, `anchor:`, and reconciliation. |
| `classes` | string or list | Optional, repeatable categories. Selected on by [stylesheets](#stylesheets). |
| `id` | — | **Assigned by the loader.** Never author one. |
| `style` | mapping | See [Style properties](#style-properties). |
| `text` | string | Label, or an icon name for `Icon`/`IconButton`/`Fab`. |
| `value` | string | State binding — what a control *is*. See [Bindings](#bindings). |
| `supporting_text` | string | Second line, trailing text, or action label, per widget. |
| `open` | string | Whether an overlay is showing. Templated like `value`. |
| `disabled` | string | Whether the control is inert. Templated. Inherited by children. |
| `handlers` | mapping | `on_*` keys to handler names registered in Python. |
| `children` | list | Child nodes. |

### `name` versus `classes`

`name` is an identity and must be unique — a duplicate is rejected at load,
because `find()` would otherwise silently return the wrong node. `classes` is a
category and repeats freely:

```yaml
- name: save_btn          # exactly one node is 'save_btn'
  classes: action primary # many nodes may be 'action'
  widget: Button
```

Only name what something references. A handler names a *function*, not a node,
so a button with an `on_click:` needs no `name`.

Leaving a node unnamed has one cost, and it is worth understanding: an unnamed
node's state is bound to its **position**, so after a reorder the element at
index 0 is reused and given the other node's spec. For a `Divider` that is
meaningless; for anything holding focus, scroll, or text, give it a name.

---

## Bindings

`text`, `value`, `open`, and `supporting_text` accept `{{ expression }}`
templates evaluated against signals exposed from Python:

```yaml
- name: count
  widget: Text
  text: "Clicked {{ clicks.get() }} times"

- name: dark_toggle
  widget: Switch
  value: "{{ dark.get() }}"
```

```python
app.expose(clicks=Signal(0), dark=Signal(True))
```

Expressions run in a sandbox. Attribute access, comprehensions, lambdas,
imports, and dunder access are rejected — a view file is exactly the kind of
artefact people copy from the internet.

Conditionals work, which is how a widget changes icon or label:

```yaml
text: "{{ 'favorite' if saved.get() else 'favorite_border' }}"
```

---

## Handlers

```yaml
handlers:
  on_click: save
```

```python
@app.handler
def save(event) -> None: ...
```

Available keys: `on_click`, `on_pointer_down`, `on_pointer_up`,
`on_pointer_move`, `on_pointer_enter`, `on_pointer_leave`, `on_wheel`,
`on_key_down`, `on_text`, `on_focus`, `on_blur`.

An unknown handler name fails at mount, not at the first click.

### Handlers run in two phases

An event travels down to the target (capture) and back up (bubble), and a
handler you declare is invoked in **both**. That lets an ancestor intercept an
event before the target ever sees it — call `event.stop_propagation()` during
capture and the target never runs.

The consequence is worth knowing: a handler on an **ancestor** of the target
runs **twice** for one event. Check the phase when that matters:

```python
@app.handler
def on_card_click(event) -> None:
    if event.phase is not Phase.CAPTURE:
        ...   # runs once, on the way back up
```

A handler on the target itself runs once, so the common case is unaffected.

---

## Composition

A view can pull in another file, so shared pieces live once:

```yaml
- name: card
  source: parts/info_card.yaml
  with:
    title: "Storage"
    body: "42% used"
```

The included file declares its interface:

```yaml
params: [title, body]
widget: Card
children:
  - {widget: Text, text: "{{ title }}"}
  - {widget: Text, text: "{{ body }}"}
```

There are no merge rules: a call site passes `name:`, `source:`, and `with:`,
and everything the fragment needs to be told must be a declared `param`. Names
inside a fragment are namespaced by the call site (`card.title`), so including
one twice does not collide. Includes cannot escape the view directory.

---

## Overlays

Content that floats above the tree — dialogs, menus, tooltips, snackbars,
sheets. Declared at the top level rather than nested, because an overlay is not
laid out or clipped by whatever opened it.

```yaml
overlays:
  - name: menu
    widget: Menu
    open: "{{ menu_open.get() }}"
    style: {anchor: menu_btn}      # implies placement: anchor
    children:
      - {widget: MenuItem, text: Cut, supporting_text: "Ctrl+X"}
```

| Property | Effect |
|---|---|
| `placement` | `center`, `anchor`, `top`, `bottom`, `left`, `right` |
| `anchor` | `name:` of the element to attach to |
| `modal` | blocks input to everything beneath |
| `scrim` | draws M3's 32% backdrop |
| `dismissable` | closes on Escape or a click outside (default `true`) |
| `offset` | gap from the anchor, in dp |

Most components know where they belong: `BottomSheet` and `Snackbar` default to
`bottom`, `SideSheet` to `right`, `Dialog` to `center`. Setting `anchor:` alone
implies `placement: anchor`. Declaration order is z-order.

---

## Stylesheets

`styles:` is a list of rules applied to every node before the interface is
built. It is what `classes:` exists for.

```yaml
styles:
  - style: {corner_radius: 12}                      # baseline: everything
  - widget: Button
    style: {height: 44, width: 150}
  - classes: danger
    style: {background: error, color: on_error}
  - name: confirm
    style: {width: 220}

root:
  widget: Column
  children:
    - {name: save,    widget: Button, text: Save}
    - {name: confirm, widget: Button, classes: danger, text: Confirm}
```

A rule matches on any combination of `widget:`, `classes:` (**all** listed
classes must be present), and `name:`. A rule with no selector matches
everything, which is how you set a baseline.

### Precedence

Lowest to highest:

1. rules with no selector
2. `widget:` rules
3. `classes:` rules — more classes beat fewer
4. `name:` rules
5. the node's own inline `style:`

Ties within a level go to document order, later winning — the same rule CSS
uses. **Rules merge rather than replace:** each contributes only the properties
it actually sets, so a `widget:` rule setting `height` and a `classes:` rule
setting `background` both apply.

### What it costs

Nothing per frame. Rules are folded into each node's style once, at load, so
layout and paint read `style` exactly as they do for a hand-written one.
Changing a stylesheet is a reload, which hot reload already handles — and
because reloading reconciles rather than replaces, restyling a running
application keeps focus, scroll, and text.

Selectors are structured rather than CSS-like strings, deliberately: a `#name`
selector would need quoting in every rule, because YAML reads `#` as a comment.

## Disabled controls

`disabled:` marks a control inert. It is templated like `value:`, so it tracks
a signal:

```yaml
- name: save
  widget: Button
  text: Save
  disabled: "{{ not form_valid.get() }}"
  handlers: {on_click: save}
```

A disabled control ignores the pointer, never shows hover or press, and is
skipped by Tab — leaving it keyboard-reachable when the mouse cannot touch it
is the accessibility failure the state exists to avoid. **Disabling a container
disables everything inside it**, which is how you grey out a whole form section.

It repaints per M3: the container becomes `on_surface` at 12% and the content
`on_surface` at 38%. Note that M3 *replaces* the colours rather than dimming the
control's own, so a disabled filled button and a disabled outlined one look
alike — that is intended.

## Widgets

Dimensions are Material Design 3's own dp figures. pyCopper's logical units map
to dp 1:1, so an M3 `40dp` control is `height: 40`.

### Layout primitives

| Widget | Notes |
|---|---|
| `Container` | A styled box with padding and at most one child. |
| `Row` / `Column` | Lay children along an axis. `spacing`, `main_alignment`, `cross_alignment`. |
| `Stack` | Overlays children; positioned with `align_x` / `align_y`. |
| `Spacer` | Empty space. `width: expand` pushes siblings apart. |
| `ScrollView` | A clipped viewport. **Must** have a bounded size on its scroll axis. |

Inside a `Row` or `Column`, a child with `width: expand` (or `flex`) on the main
axis shares the free space; anything else is measured first and takes what it
needs. A `Text` shrink-wraps to its ink, so it will not starve its siblings.

### Content

| Widget | Notes |
|---|---|
| `Text` | Shaped, kerned, wrapped. `font_size` in dp. |
| `Icon` | Material Symbols. Name goes in `text:`; `icon_size`, `icon_fill`, `icon_weight`. |
| `Divider` | 1dp `outline_variant`. `full_bleed` / `inset`. |

### Buttons and controls

| Widget | M3 spec |
|---|---|
| `Button` | 40dp high, full radius. `filled`, `filled_tonal`, `outlined`, `elevated`, `text`. |
| `IconButton` | 40dp container, 24dp icon. `standard`, `filled`, `filled_tonal`, `outlined`. |
| `Fab` | 56dp standard, 40 small, 96 large. |
| `Checkbox` | 18dp box, 2dp radius. |
| `Radio` | 20dp outer, 10dp dot. |
| `Switch` | 52×32dp track. |
| `Chip` | 32dp high. `assist`, `filter`, `input`, `suggestion`. |
| `Badge` | 6dp dot, or a 16dp pill carrying `value:`. |

Selection is a **binding, not style**: `value: "{{ checked.get() }}"`.

### Structure

| Widget | M3 spec |
|---|---|
| `Card` | 12dp radius, 16dp padding. `elevated`, `filled`, `outlined`. |
| `ListItem` | 56 / 72 / 88dp by line count. |
| `TopAppBar` | 64dp small, 112dp `medium`, 152dp `large`. |
| `NavigationRail` + `NavItem` | 80dp wide, 56×32dp indicator. |
| `NavigationDrawer` | 240–360dp, 56dp items. |
| `Tabs` + `Tab` | 48dp, 3dp indicator. `primary`, `secondary`. |
| `SegmentedButton` + `Segment` | 40dp, 20dp outer corners. |

A selection container carries `value:` naming the selected child by `name`.

### Collapsing app bars

A `medium` or `large` app bar shrinks into a small one as its page scrolls,
which M3 describes as transforming "into small app bars... until the page is
scrolled back to the top". Name the scrolling view:

```yaml
- name: bar
  widget: TopAppBar
  text: Inbox
  style: {variant: large, collapses_with: body, width: expand}
- name: body
  widget: ScrollView
  style: {height: expand, width: expand}
  children: [ ... ]
```

The height is a direct function of the scroll offset — there is no animation
clock involved, so it tracks a drag exactly. The container also fills with
`surface_container` as it collapses, which is M3's own way of separating the
bar from the content beneath.

Without `collapses_with:` a medium or large bar simply stays expanded.

### Progress

| Widget | M3 spec |
|---|---|
| `LinearProgress` | 4dp, rounded ends. |
| `CircularProgress` | 4dp ring, clockwise from 12 o'clock. |

Supplying `value:` (the fraction, 0 to 1) gives the determinate form.
**Omitting `value:` entirely** gives the indeterminate form, which animates
continuously — a bar that grows, travels and shrinks, or a rotating arc. An
indicator bound to a signal that starts empty therefore changes from
indeterminate to determinate on its own as information arrives, which is what
M3 asks for.

### Carousel

| Widget | Notes |
|---|---|
| `Carousel` | `uncontained` (items keep their width, free scroll), `hero` (large + small), `multi_browse` (large + medium + small). |
| `CarouselItem` | 28dp radius. Sized by the strip, not by itself. Its children parallax as the strip moves; its `text:` label sits over them. |

`hero` and `multi_browse` resize their items and snap by item; `uncontained`
scrolls by pixels.

### Overlay components

| Widget | M3 spec |
|---|---|
| `Dialog` | 28dp radius, 24dp padding, 280–560dp, height dynamic. |
| `Menu` + `MenuItem` | 4dp radius, 112–280dp / 48dp rows. |
| `Tooltip` | 24dp high, `inverse_surface`. |
| `Snackbar` | 48dp growing to 64dp; `supporting_text` is the action label. |
| `BottomSheet` | 28dp top corners, max 640dp, optional `handle`. |
| `SideSheet` | 16dp leading corners, max 400dp. |

---

## Style properties

### Size and space

| Property | Values |
|---|---|
| `width`, `height` | a number (dp), `expand`, or a percentage like `50%` |
| `padding`, `margin` | one number, or `[left, top, right, bottom]` |
| `spacing` | gap between children of a `Row`/`Column` |

### Colour and shape

| Property | Values |
|---|---|
| `background` | an MD3 token name, e.g. `surface_container` |
| `color` | content colour; defaults to the widget's own M3 role |
| `corner_radius` | one number, or `[tl, tr, br, bl]` |
| `border` | `{width, color}` |
| `shadow` | `{blur, offset_x, offset_y, color, opacity}` |
| `opacity` | 0–1 |

Colours are **token names, not hex** — that is what makes a theme switch a
single buffer upload. There are 59 tokens; `pycopper.is_token()` checks one and
`TOKEN_ORDER` lists them all. An unknown token fails at load with a path.

### Alignment

| Property | Values |
|---|---|
| `main_alignment` | `start`, `end`, `center`, `space_between`, `space_around`, `space_evenly` |
| `cross_alignment` | `start`, `end`, `center`, `stretch` |
| `align_x`, `align_y` | 0–1, for `Stack` children |

### Text and icons

| Property | Values |
|---|---|
| `font_size` | dp |
| `icon_size` | dp, default 24 |
| `icon_fill` | 0–1. M3 uses this for selected state — prefer it to swapping icon names. |
| `icon_weight` | 100–700 |

### Component-specific

| Property | Applies to |
|---|---|
| `variant` | most components; the valid names are per widget |
| `thickness` | `Divider`, `CircularProgress` |
| `inset` | `Divider` |
| `axis` | `ScrollView` — `vertical` (default) or `horizontal` |
| `scrollbar` | `ScrollView` — show the indicator when content overflows |
| `handle` | `BottomSheet` — draw the drag handle |
| `collapses_with` | `TopAppBar` — `name:` of the `ScrollView` it collapses with |
| `placement`, `anchor`, `modal`, `scrim`, `dismissable`, `offset` | overlays |

---

## What does not exist yet

Stated plainly so you can design around it:

- **Motion.** Animated: overlay fades, state layers, every selection control,
  tab and navigation indicators, indeterminate progress, a carousel's snap and
  content parallax, and app-bar collapse. Set `reduce_motion` in `Settings` to
  make timed transitions arrive at once — it does not affect app-bar collapse
  or carousel parallax, which follow a position rather than a clock.
- **The M3 type scale as named roles.** Widgets take a raw `font_size`;
  `label-large` and friends are not modelled.
- **Tonal elevation.** M3 elevation is a tonal surface shift *plus* a shadow;
  only the shadow is modelled.
- **Drag gestures.** A bottom sheet's drag handle and a scrollbar's thumb are
  drawn but do not respond to a drag; both are affordances for a gesture that
  is not wired to the pointer yet.
- **Separate hit and paint rects**, so M3's 48dp minimum touch target cannot be
  expressed on a smaller visible control. This is deliberate — pyCopper is
  pointer-only.
- **Right-click menus, cursor shapes, and mouse text selection.**
