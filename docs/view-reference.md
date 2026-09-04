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
| `view` | — | **Assigned by the loader.** The view file this node was written in. |
| `style` | mapping | See [Style properties](#style-properties). |
| `text` | string | Label, or an icon name for `Icon`/`IconButton`/`Fab`. |
| `value` | string | State binding — what a control *is*. See [Bindings](#bindings). |
| `supporting_text` | string | Second line, trailing text, or action label, per widget. |
| `open` | string | Whether an overlay is showing. Templated like `value`. |
| `disabled` | string | Whether the control is inert. Templated. Inherited by children. |
| `error` | string | Whether a `TextField` is showing an error. Templated like `disabled`. |
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

Available keys: `on_click`, `on_context_menu`, `on_pointer_down`,
`on_pointer_up`, `on_pointer_move`, `on_pointer_enter`, `on_pointer_leave`,
`on_wheel`, `on_key_down`, `on_text`, `on_focus`, `on_blur`, `on_change`,
`on_dismiss`.

`on_change` is the odd one: it is posted by a widget rather than by the window,
and its event carries `event.value` — the new text — so a handler does not have
to reach back into the field to find out what it is. `on_dismiss` is posted by
the overlay layer when the *runtime* closes an overlay — Escape, or a press
outside a dismissable one — so an application can clear whatever signal its
`open:` is bound to. See [Two ways for a dialog to behave](#two-ways-for-a-dialog-to-behave).

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
        ...  # runs once, on the way back up
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
| `placement` | `center`, `anchor`, `pointer`, `top`, `bottom`, `left`, `right` |
| `anchor` | `name:` of the element to attach to |
| `modal` | blocks input to everything beneath |
| `scrim` | draws M3's 32% backdrop |
| `dismissable` | closes on Escape or a click outside (default `true`) |
| `offset` | gap from the anchor, in dp |
| `has_submenu` | a `MenuItem` draws a trailing `chevron_right` instead of `supporting_text` — see below |

### Submenus

A `MenuItem` that opens a submenu carries `has_submenu: true`, which draws a
trailing `chevron_right` in place of `supporting_text`. The submenu itself is
a second `Menu` overlay, declared *after* the parent menu, anchored to the
item's `name`:

```yaml
overlays:
  - name: main
    widget: Menu
    open: "{{ menu_open.get() }}"
    style: {anchor: menu_btn}
    children:
      - {name: new, widget: MenuItem, text: New}
      - name: recent
        widget: MenuItem
        text: Open Recent
        style: {has_submenu: true}
        handlers: {on_pointer_enter: openRecent}
  - name: recent_menu
    widget: Menu
    open: "{{ recent_open.get() }}"
    style: {anchor: recent}       # a name inside the OTHER overlay above
    children:
      - {widget: MenuItem, text: report.docx}
```

An anchor that names something inside another overlay resolves there once the
main tree has no match — this is the one case an anchor target is not a plain
widget. Anchoring to a `MenuItem` specifically also changes *how* it
positions: beside the item (flipping to the other side near an edge) rather
than below it, matching M3's stated submenu placement.

### Two ways for a dialog to behave

These three properties combine into the two behaviours a modal dialog usually
wants, and the difference is only `dismissable`.

**Dismissable** — clicking outside closes it. Wire `on_dismiss`, because that
is what actually closes it:

```yaml
- name: confirm
  widget: Dialog
  open: "{{ confirming.get() }}"
  style: {modal: true, scrim: true}          # dismissable defaults to true
  handlers: {on_dismiss: close_confirm}      # sets confirming to false
```

**Locked** — the parent is dimmed and unclickable, focus cannot leave, and the
dialog closes only through its own buttons:

```yaml
- name: confirm
  widget: Dialog
  open: "{{ confirming.get() }}"
  style: {modal: true, scrim: true, dismissable: false}
```

The gallery has one of each, built from the same `Dialog` and one property
apart: `parts/confirm_dialog.yaml` and `parts/locked_dialog.yaml`.

**`on_dismiss` is not optional for a dismissable overlay whose `open:` is
bound**, which is every overlay an application controls. The runtime closing it
is a *request*: the binding still says open, so without a handler to clear the
signal the overlay would reopen on the next frame. Escape goes through the same
path, so one handler covers both.

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

### Sharing a sheet across files

A `styles:` entry of the form `- source:` splices in the rules that file names,
so a theme lives in one place:

```yaml
# theme.yaml -- a bare list of rules
- classes: action
  style: {width: 100, height: 40, variant: outlined}
- classes: action primary
  style: {variant: filled}
```

```yaml
# view.yaml
styles:
  - source: theme.yaml
  - widget: Button          # a local override: later, so it wins the tie
    style: {height: 48}
```

Rules land **in place**, so ordering reads as written — an import placed after
a local rule overrides it, not the other way round. A sheet may import another.

Every file is watched by hot reload, so editing a theme restyles a running
application without losing focus, scroll, or text.

A stylesheet is a **list**; a widget fragment is a **mapping**. Including one
where the other belongs says so directly rather than failing later as a
confusing error about a file that was perfectly valid. The same guards apply as
to widget includes: no escaping the view directory, no cycles, and a depth
limit.

**Do not use a selector-less rule to set `corner_radius` or other shape
properties globally.** It would override each component's own M3 shape — a
`Button` is a pill at half its height, a `Card` is 12dp — and flatten the
catalogue to one radius. A stylesheet is for the choices an application makes,
not for overwriting the design system beneath it.

### What it costs

Nothing per frame. Rules are folded into each node's style once, at load, so
layout and paint read `style` exactly as they do for a hand-written one.
Changing a stylesheet is a reload, which hot reload already handles — and
because reloading reconciles rather than replaces, restyling a running
application keeps focus, scroll, and text.

Selectors are structured rather than CSS-like strings, deliberately: a `#name`
selector would need quoting in every rule, because YAML reads `#` as a comment.

## Type scale

M3 defines fifteen type roles, from `display-large` to `label-small`. Name one
with `text_style:` instead of a raw size:

```yaml
type_scale:
  title-large: 22
  body-medium: 14

root:
  widget: Column
  children:
    - {widget: Text, text: Heading, style: {text_style: title-large}}
    - {widget: Text, text: Body,    style: {text_style: body-medium}}
```

A scale can live in its own file and be shared, like a stylesheet:

```yaml
type_scale: {source: typescale.yaml}
```

Roles resolve to `font_size` once at load, so nothing is paid per frame, and a
role beats an explicit `font_size` on the same node.

### The built-in scale

All fifteen roles work without declaring anything; `type_scale:` overrides them
role by role.

| | large | medium | small |
|---|---|---|---|
| **display** | 57 | 45 | 36 |
| **headline** | 32 | 28 | 24 |
| **title** | 22 | 16 | 14 |
| **body** | 16 | 14 | 12 |
| **label** | 14 | 12 | 11 |

**Where these come from.** The spec page at
<https://m3.material.io/styles/typography/type-scale-tokens> serves a
JavaScript shell with no table in the delivered HTML — which is why the copy in
this project's reference library is empty. The figures instead come from
Google's autogenerated token source in the Material Web Components repository
(`tokens/versions/latest/sass/_md-sys-typescale.scss`, Material 3 version
**34.0.21**), converted from `rem` at 16px/rem.

They agree with every value the reference library corroborates independently,
and settle the one it contradicts itself on: `headline-large` appears there as
both 32sp and 36sp, and the token source says **32**. Tests pin both facts.

A role carries three more tokens beside its size: **weight**, **tracking** and
**line height**. `title-medium`,
`title-small` and every `label-*` role are Medium (500), the rest Regular
(400); Roboto ships both faces, so those are genuinely Medium rather than
emboldened Regular. Tracking becomes `letter_spacing`, and nine of the fifteen
roles have some — `body-large` and the two smallest labels the most, at half a
pixel, and `display-large` the only negative one at −0.25.

| | tracking |
|---|---|
| `display-large` | −0.25 |
| `title-medium` / `body-small` | 0.15 / 0.4 |
| `title-small` / `label-large` | 0.1 |
| `body-medium` | 0.25 |
| `body-large`, `label-medium`, `label-small` | 0.5 |
| everything else | 0 |

Line height becomes `line_height`, a fixed height in logical px replacing the
font's own. The two do not differ much, and not always in the same direction:
Roboto wants 67px at `display-large` where M3 asks for 64, and 19px at
`body-large` where M3 asks for 24.

An explicit `font_weight:`, `letter_spacing:` or `line_height:` beside a role
wins — naming a role states an intent, and writing one of these beside it
states a more specific one. Overriding a role's size in `type_scale:` leaves
all three alone: they are separate tokens, and resizing a role says nothing
about them.

Tracking is **absolute**, in logical px, the way M3 states it — it does not
scale with `font_size`, so a role's tracking is only right at that role's size.
It is added after every grapheme cluster, including the last on a line, as CSS
`letter-spacing` is. That leaves centred text off-centre by half a tracking
value, a quarter-pixel at the largest figure in the scale; the alternative is
special-casing line ends in the measurement, the caret and the paint pen
separately, and those three drifting apart is a worse bug than a quarter-pixel.

Line height is **absolute** too, and the extra space is split evenly above and
below the glyphs, the way CSS distributes half-leading. That has a useful
consequence: raising a line's height does not move centred text. A button's
label measures 20px tall instead of 17 and sits in exactly the same place. Text
positioned from its *top* does move, by half the difference.

A line height shorter than the font's own is allowed and does occur in the
scale; the leading is simply negative, and lines close up rather than the
glyphs being cropped.

## ViewModels

A view file can own its logic. One view, one ViewModel — the familiar MVVM
shape, with the naming convention enforced rather than suggested.

```python
# parts/swatch_ViewModel.py
from pycopper import Signal, ViewModel


class Swatch(ViewModel):
    picked = Signal(False)

    def pick(self, event) -> None:
        self.picked.set(True)
```

```yaml
# parts/swatch_View.yaml
name: swatch
widget: Container
style: {background: "{{ 'primary' if picked.get() else 'surface' }}"}
handlers: {on_click: pick}
```

```python
# app.py -- the entry point, and the composition root
app.bind_view_model("parts/swatch_View.yaml", Swatch())
```

Public attributes become names the view's `{{ }}` can read; public methods
become handlers its `handlers:` can name. Nothing is registered twice.

**Binding is explicit, and deliberately not by filename.** A view file naming
its own Python module would let data decide what gets imported, and view files
are untrusted input here — `yaml.safe_load` only, includes confined to the view
directory, no `eval`. The application imports its own code and says what pairs
with what. The convention is then *checked*: a bound view must be
`*_View.yaml` and its ViewModel must live in `*_ViewModel.py`, or binding
raises. Views without a ViewModel need no suffix.

**Resolution order** is the view's own ViewModel, then the application's
`expose`/`handler` registry. Local wins, so a fragment can name things without
knowing what the rest of the application calls them, and an application-wide
signal still reaches a nested view without being threaded through every
include.

**One view file, one ViewModel.** Including a fragment five times gives five
copies of the *view* and one ViewModel behind them — right for logic belonging
to the view, so per-instance state stays on the widget's own `state`.

**Sharing between ViewModels is Python's job.** A parameter is textual
substitution into YAML, so a child cannot be handed an object through `with:`.
Pass it to the child's constructor where the application composes them — the
gallery's `app.py` hands its dialogs the signal each one opens on, and each
dialog publishes it under its own view's name.

Two consequences worth knowing:

- An expression written at a *call site* and passed through `with:` is
  evaluated in the *fragment's* scope, because that is where the node ends up.
  Give the fragment's ViewModel the name instead of borrowing the parent's.
- `self.app` reaches the application for the few things that genuinely are its
  own — switching the theme is the honest example. It is deliberately not
  visible to `{{ }}` expressions.

## Accessibility

pyCopper builds the semantic tree — roles, names, states, bounds — and an
optional bridge pushes it to the platform.

```python
from pycopper.runtime.accesskit_bridge import AccessKitBridge, available

if available() is None:  # a sentence when it cannot run
    app.bind_accessibility(AccessKitBridge(window_title="My app"))
```

**It is opt-in and Linux-only today.** The bridge needs `accesskit`, a native
wheel, so it is an extra: `pip install 'pycopper[a11y]'`. AccessKit ships its
Windows and macOS adapters in their own platform wheels, so this build serves
AT-SPI and `available()` says so rather than leaving it to be discovered.
Without a bridge bound, nothing reaches a screen reader.

```python
tree = app.accessibility_tree()
confirm = tree.find(role="button", name="Confirm")
assert confirm.bounds.width == 130
```

The tree is worth having with or without a bridge: it is what the bridge is
handed, and it lets a test ask for *the button called Confirm* rather than for
a rectangle at some coordinate.

A reader can also *operate* the interface — every clickable role advertises the
click action, and requests are applied on the engine thread a frame later,
because AccessKit delivers them from its own D-Bus thread and pyCopper's
signals are thread-affine.

**Roles are sourced where M3 states one** — a text field is `textbox`, a
progress indicator has the "role of 'progressbar'", a navigation item is `tab`,
and a navigation *container's* "role is not announced". The rest follow ARIA
convention, and the module marks which is which rather than smoothing over the
difference.

Three rules worth knowing when writing views:

- **`name:` is never announced.** It is a developer handle; reading out
  `sw_primary` would be worse than silence. It travels as `key` so tests can
  still find a node by it.
- **An icon name is never announced.** For `Icon`, `IconButton`, `Fab` and
  `NavItem`, `text:` holds a Material Symbols glyph name, so the label comes
  from `supporting_text:`. **An icon-only control with no `supporting_text:`
  has no accessible name at all** — that is a real gap in a view, and the tree
  reports an empty name rather than inventing one.
- **Layout and decoration disappear.** A `Spacer` is dropped entirely and a
  silent container's children are lifted into its place, so a reader never
  walks through a level that says only "group".

Visible overlays are appended to the root, because a dialog is not a child of
what it covers; a closed one is absent entirely rather than present-but-hidden.

## Hit targets

A control is clickable at the size it is drawn, which on a pixel-precise
pointer is what you want. Two properties widen that without touching anything
else:

```yaml
- name: agree
  widget: Checkbox
  style: {min_hit_size: 48}      # M3's "at least 48x48dp", on an 18dp box
```

`min_hit_size` is a minimum square centred on the painted control, and it is
the way to write M3's rule: the figure stays correct when the control's size
changes, where padding worked out by hand does not. `hit_padding` takes the
same forms as `padding` — one number, or `[left, top, right, bottom]` — for the
asymmetric cases a minimum cannot state.

**Neither affects layout or paint.** The control keeps its size, its neighbours
keep their positions, and what is drawn is identical. Only where clicks, hover,
and the cursor shape are picked up changes.

Three things worth knowing:

- A widened target **reaches outside its parent** if it needs to. A 48dp target
  on an 18dp checkbox in a 40dp row extends past the row, and clicks there
  still arrive.
- Two widened targets **can overlap** where the drawn controls do not. M3 asks
  for 8dp between targets and nothing here enforces it; where they overlap, the
  one drawn later wins, exactly as overlapping paint does.
- A widget that **clips** its children — `ScrollView`, `Carousel`,
  `SegmentedButton` — clips their targets too. A control scrolled just past the
  edge does not take clicks it cannot visibly respond to.

## Text fields

The only widget that takes typing.

```yaml
- name: email
  widget: TextField
  text: "Email"                     # the label
  value: "{{ email.get() }}"        # the content
  supporting_text: "We never share it"
  error: "{{ not valid.get() }}"
  style: {variant: outlined, width: 320}
  handlers: {on_change: set_email}
```

`text:` is the label, `value:` is the content and `supporting_text:` is the
line beneath — the same three fields every other widget already has, rather
than a `label:` invented for one component. Binding `value:` makes the field
controlled: the application can put text into it at any point, and each edit
fires `on_change` with the new value.

The label "floats upward to 12sp typography scale when focused or populated" —
M3's words, and the reason it animates between `body-large` and `body-small`
rather than between two chosen numbers. `variant: filled` (the default) has a
1dp bottom indicator that thickens to 2dp on focus; `variant: outlined` has a
border that does the same.

**What the keyboard does:**

| Keys | Effect |
|---|---|
| Arrows | Move by grapheme cluster; Home / End go to the ends |
| Ctrl+arrows | Move by word |
| Shift+anything | Extend the selection instead of moving |
| Backspace / Delete | Remove the selection, or one cluster; Ctrl to take a word |
| Ctrl+A / C / X / V | Select all, copy, cut, paste |
| Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y | Undo and redo |

A run of typing is **one undo step**. The run breaks when the caret moves, when
a selection is replaced, or when a deletion intervenes — the three rules a text
editor uses, so undo takes back a word rather than a letter.

Editing is by **grapheme cluster** throughout: backspace removes an accented
character rather than its accent, and the caret never lands inside a flag
emoji. Word boundaries are whitespace-delimited, not UAX #29 — the same rule
double-click uses, so the two always agree.

**Three shapes, and M3 names all three.** A plain field is one line: text
longer than the box scrolls sideways to follow the caret, and scrolls back
rather than leaving empty space when you delete.

```yaml
- {name: note, widget: TextField, text: "Note", style: {multiline: true}}
- {name: body, widget: TextField, text: "Body",
   style: {multiline: true, height: 140}}
```

`multiline: true` gives M3's **multi-line field**, which "grows to accommodate
multiple lines of text" and "initially appears as a single-line field" — so an
empty one is exactly 56dp and it expands by a line at a time as the text wraps.
Adding a `height:` gives M3's **text area**: "fixed-height fields" that "scroll
vertically when the cursor reaches the bottom". The difference between the two
forms is only whether you fixed a height, so there is no second property.

In a multi-line field **Enter inserts a newline**; in a single-line one it is
left alone, so a view can put a handler on it. **Up and Down move by a line as
drawn**, preserving the column, so arrowing down from the end of a short line
lands at the same horizontal position on the next one rather than at its start.
Home and End become line-relative, and End stops before the newline.

Copy and paste use the system clipboard — see [The clipboard](#the-clipboard).

## Text selection

A `Text` widget with `selectable: true` can be selected with the mouse:

```yaml
- name: quote
  widget: Text
  text: "Selectable, and copyable with Ctrl+C."
  style: {selectable: true, width: 400}
```

Click to place a caret, drag to extend, double-click for a word, **Ctrl+A** for
all of it, **Ctrl+C** to copy. Selection moves by **grapheme cluster**, so an
edge never lands inside a flag emoji or between a letter and its accent. A
selectable block takes focus and shows a text cursor.

It is **off by default**, because a selectable label shows a text cursor and
swallows drags — wrong for the labels most text in an interface is.

### The clipboard

**Ctrl+C and Ctrl+V use the system clipboard.** This previously said pyCopper
shipped none, on the grounds that the only route was the backend's private
window handle. That was wrong: GLFW's clipboard functions take the window as a
*deprecated* parameter and accept `None`, so no private state is involved. A
window is created, GLFW is initialised, and the backend is installed.

Two constraints are worth knowing, both from Wayland rather than from pyCopper:

- **Reading needs keyboard focus.** A client may only read the selection while
  focused. That is always true of a user pressing Ctrl+V, and never reliably
  true of a program driving the clipboard by itself.
- **Writing needs a recent input event.** A compositor accepts a new selection
  only with a serial from a real keystroke or click behind it. Again: true of
  Ctrl+C, not of a background thread.

A read that comes back empty falls back to whatever this process last copied,
so pasting inside an application keeps working when the system read is refused.
The trade is that clearing the clipboard elsewhere does not clear this one.

An application can still install its own backend, which takes precedence:

```python
from pycopper.runtime.clipboard import clipboard
import pyperclip


class SystemClipboard:
    def set_text(self, text: str) -> bool:
        pyperclip.copy(text)
        return True

    def get_text(self) -> str:
        return pyperclip.paste()


clipboard.install(SystemClipboard())
```

### What is not implemented

- **Editing.** This is selection on a `Text`, which is read-only. For typing,
  use [`TextField`](#text-fields).
- **Selection across widgets.** A drag selects within one `Text`.
- **Bidirectional text.** Selecting across a left-to-right / right-to-left
  boundary is not handled; the highlight is contiguous in character order,
  which is not what a bidi caret should do (ARCHITECTURE risk R9).
- **UAX #29 word boundaries.** Double-click uses whitespace delimiting, which
  is simple and predictable rather than Unicode-correct.

The pointer changes shape over what it is on, without you asking:

| Over | Shape |
|---|---|
| anything clickable — button, checkbox, radio, switch, chip, menu item | `pointer` |
| a **disabled** control | `not-allowed` |
| a scrollbar thumb | `ns-resize` / `ew-resize` |
| a bottom sheet's drag handle | `ns-resize` |
| everything else | `default` |

`cursor:` overrides it on any node. The topmost element with an opinion wins, so
a button inside a container gets the button's shape and the container keeps its
own everywhere the button does not reach.

An unknown name fails at load rather than from inside a frame.

## Context menus

A right-click fires `on_context_menu`, and an overlay with `placement: pointer`
opens where the click happened:

```yaml
root:
  children:
    - name: canvas
      widget: Container
      handlers: {on_context_menu: show_menu}

overlays:
  - name: ctx
    widget: Menu
    open: "{{ menu_open.get() }}"
    style: {placement: pointer}
    children:
      - {widget: MenuItem, text: Cut,  supporting_text: "Ctrl+X"}
      - {widget: MenuItem, text: Copy, supporting_text: "Ctrl+C"}
```

```python
@app.handler
def show_menu(event) -> None:
    menu_open.set(True)
```

The event carries the point that was clicked, and the menu opens down and to the
right of it — flipping near an edge rather than being clipped. It closes on a
click outside or on Escape, like any other dismissable overlay.

A secondary press does **not** press, focus, or click the thing under it, so
right-clicking a button does not leave it stuck looking pressed.

## Elevation

M3 gives every component a resting **level**, 0 to 5, and each level a dp
height. A level says where a surface sits relative to others; the height is
what produces a shadow.

| Level | Height | Components that rest there |
|---|---|---|
| 0 | 0dp | filled/tonal/outlined buttons, filled/outlined cards, chips, tabs, lists, rail |
| 1 | 1dp | elevated button, elevated card, modal bottom sheet, modal side sheet, modal drawer |
| 2 | 3dp | menu, scrolled app bar, rich tooltip |
| 3 | 6dp | FAB, modal dialog |
| 4–5 | 8/12dp | not resting levels — reserved for interacted states |

Components take their own level, so you rarely set one:

```yaml
- {name: fab, widget: Fab, text: add}                    # level 3, from M3
- {name: flat, widget: Fab, style: {elevation: 0}}       # deliberately flat
```

Hovering or focusing something already raised lifts it one level, which is what
M3 describes. A level-0 component stays flat — a filled button growing a shadow
under the pointer is not what the spec means.

**On tonal elevation.** M3 used to express elevation partly as a surface *tint*
overlay. That mechanism is **deprecated**: "Surface tint color is deprecated.
Use elevation level tokens (0–5) instead." Tonal separation now comes from
choosing among the `surface` and `surface_container_*` roles, which the spec
says are "not tied to elevation" — so picking a container role and setting a
level are two independent decisions, and pyCopper treats them that way.

## Dragging

Two things respond to a drag, and both are affordances that would otherwise be
decoration:

- **A scrollbar's thumb.** Grab it anywhere it is drawn — plus a few pixels
  either side, because a 4dp target is unusable with a mouse — and the content
  keeps pace with the pointer.
- **A bottom sheet's drag handle.** Drag the sheet down; release past about a
  third of its height to dismiss it, or short of that to let it settle back.
  Clicking the handle closes the sheet, which is the single-pointer alternative
  M3 requires: *"selecting the drag handle should toggle through preset heights
  or close the sheet"*. Preset heights are not implemented.

A sheet without `handle: true` cannot be dragged. Drawing the affordance is
what promises the gesture.

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
| `TextField` | The editable one. 56dp, `filled` or `outlined`. See [Text fields](#text-fields). |

Inside a `Row` or `Column`, a child with `width: expand` (or `flex`) on the main
axis shares the free space; anything else is measured first and takes what it
needs. A `Text` shrink-wraps to its ink, so it will not starve its siblings.

### Content

| Widget | Notes |
|---|---|
| `Text` | Shaped, kerned, wrapped. `font_size` in dp. |
| `Icon` | Material Symbols. Name goes in `text:`; `icon_size`, `icon_fill`, `icon_weight`. |
| `Divider` | 1dp `outline_variant`. `full_bleed` / `inset`. |
| `Shape` | A regular polygon: `sides`, `rotation`, `corner_radius`, `background`, `border`. 48dp unless sized. Drawn as a distance field, not a rasterised path, so every one of those is **free to animate**. |

### Buttons and controls

| Widget | M3 spec |
|---|---|
| `Button` | 40dp high, full radius, sized to its label with a 64dp floor. `filled`, `filled_tonal`, `outlined`, `elevated`, `text`. |
| `IconButton` | 40dp container, 24dp icon. `standard`, `filled`, `filled_tonal`, `outlined`. |
| `Fab` | 56dp standard, 40 small, 96 large. |
| `Checkbox` | 18dp box, 2dp radius. |
| `Radio` | 20dp outer, 10dp dot. |
| `Switch` | 52×32dp track. |
| `Chip` | 32dp high. `assist`, `filter`, `input`, `suggestion`. |
| `Badge` | 6dp dot, or a 16dp pill carrying `value:`. |
| `Link` | Hyperlinked text: always underlined, `primary` (default) or `tertiary`. Sized with `font_size` like `Text`, not a fixed label role — it's meant to sit inline with body text. No container, no state layer. |
| `SpinBox` | A number with `remove`/`add` icon buttons either side (40dp, `IconButton`'s own anatomy). `value:` is the current number; `style: {min, max, step}` bound it (either end `None`/omitted means unbounded). Arrow keys step it too. Named to avoid M3's own "Stepper" (a multi-step flow indicator, a different widget) — not a component M3 has a page for either way. |
| `Pagination` | Prev/next arrows around page-number buttons (40dp). `value:` is the current page (1-indexed); `style: {count}` is the total. Below 8 pages every number shows; above that, only the first, last, and the current page's neighbours do, with the rest collapsed into `...`. Left/Right arrow keys step it. No M3 component — the word "pagination" appears exactly once in the whole reference library, as a prohibition on Cards. |

Selection is a **binding, not style**: `value: "{{ checked.get() }}"`.
A `SpinBox` or `Pagination` fires `on_change` with its new value already computed and clamped — the application does not do the arithmetic, only `qty.set(event.value)`.

### Structure

| Widget | M3 spec |
|---|---|
| `Card` | 12dp radius, 16dp padding. `elevated`, `filled`, `outlined`. |
| `ListItem` | 56 / 72 / 88dp by line count. |
| `Accordion` | 56 / 72dp header (M3 gives this no component of its own, only Lists' "expand and collapse" behaviour). `text:` headline + `supporting_text:`, an optional child body, `value:` for open/closed. |
| `TreeView` + `TreeItem` | Same M3 gap as `Accordion`, applied recursively. A `TreeItem` with `children:` is a branch (chevron, `value:` for open/closed); with none it's a leaf. `TreeView`'s own `value:` names the selected item by `name` at any depth. |
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
| `Popover` | M3's persistent rich tooltip. `text:` (subhead) + `supporting_text:` + an optional child action row. 12dp radius, max 320dp, **shrink-to-fit width** (unlike `Dialog`/`Menu`, no minimum). Defaults to `placement: anchor`. |
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
| `shadow` | `{blur, offset_x, offset_y, color, opacity}` — hand-tuned; prefer `elevation` |
| `elevation` | M3 level 0–5. Omit to use the component's own resting level |
| `multiline` | a `TextField` takes more than one line — see [Text fields](#text-fields) |
| `selectable` | `Text` only — can its content be selected with the mouse |
| `cursor` | pointer shape: `default`, `pointer`, `text`, `crosshair`, `ns-resize`, `ew-resize`, `nesw-resize`, `nwse-resize`, `not-allowed`, `none` |
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
| `text_style` | an M3 type-scale role, resolved against `type_scale:` |
| `font_weight` | 400 or 500 (Roboto ships both); resolves to the nearest available |
| `letter_spacing` | tracking in logical px, added after each grapheme cluster |
| `line_height` | a fixed line height in logical px; unset keeps the font's own |
| `hit_padding` | extra clickable area around the paint rect; same form as `padding` |
| `min_hit_size` | smallest clickable square, in logical px, centred on the paint rect |
| `icon_size` | dp, default 24 |
| `icon_fill` | 0–1. M3 uses this for selected state — prefer it to swapping icon names. |
| `icon_weight` | 100–700 |
| `sides` | `Shape` — 3 or more. A **float**: 5.5 is a real shape, so a square morphs continuously into a hexagon. |
| `rotation` | `Shape` — degrees, clockwise |

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
| `min`, `max`, `step` | `SpinBox` — bounds and increment; `min`/`max` default to unbounded |
| `count` | `Pagination` — total number of pages |
| `placement`, `anchor`, `modal`, `scrim`, `dismissable`, `offset` | overlays |

---

## What does not exist yet

Stated plainly so you can design around it:

- **Motion.** Animated: overlay fades, state layers, every selection control,
  tab and navigation indicators, indeterminate progress, a carousel's snap and
  content parallax, and app-bar collapse. Set `reduce_motion` in `Settings` to
  make timed transitions arrive at once — it does not affect app-bar collapse
  or carousel parallax, which follow a position rather than a clock.
- **IME preedit.** Committed characters only, so an input method that composes
  before committing — CJK, in practice — is not supported.
- **Bidirectional carets.** Text reorders correctly for display, but a caret or
  selection spanning a left-to-right / right-to-left boundary is contiguous in
  character order, which is not what a bidi caret should do.
- **Reading the clipboard without focus.** Copy and paste use the system
  clipboard, but Wayland only lets a client read the selection while it has
  keyboard focus, and only accept a *new* selection when a real input event is
  behind it. Both hold whenever a user presses Ctrl+C or Ctrl+V; neither holds
  for a program driving the clipboard on its own. A read that comes back empty
  falls back to whatever this process last copied.
- **The 48dp minimum touch target by default.** A pointer is pixel-precise, so
  a control is hit-tested at the size it is drawn. `min_hit_size:` asks for
  more where an application wants it — see [Hit targets](#hit-targets).
