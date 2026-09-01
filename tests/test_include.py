"""View composition: `source:` pulls a subtree in from another file."""

from __future__ import annotations

import textwrap
import time

import pytest

from pycopper import App, Signal, Theme
from pycopper.spec import SpecError, load_view


@pytest.fixture
def views(tmp_path):
    (tmp_path / "row.yaml").write_text(
        textwrap.dedent("""
        params: [label]
        id: item
        widget: ListItem
        text: "{{ label }}"
        style: {width: expand}
    """)
    )
    (tmp_path / "card.yaml").write_text(
        textwrap.dedent("""
        params: [title]
        id: card
        widget: Card
        style: {width: 200, height: 100}
        children:
          - {id: heading, widget: Text, text: "{{ title }}"}
    """)
    )
    return tmp_path


def write(views, body: str, name: str = "view.yaml"):
    (views / name).write_text(textwrap.dedent(body))
    return views / name


def app_for(views, body: str, **signals):
    a = App(write(views, body), theme=Theme(dark=True))
    a.expose(**signals)
    a.mount()
    a.update()
    return a


# ---------------------------------------------------------------- expansion


def test_include_expands_into_the_tree(views) -> None:
    app = app_for(
        views,
        """
        root:
          id: root
          widget: Column
          children:
            - {id: r1, source: row.yaml, with: {label: "Hello"}}
    """,
    )
    assert app.root.find("r1").text == "Hello"


def test_a_resolved_include_is_indistinguishable_from_inline(views) -> None:
    """Resolution happens before validation, so nothing downstream can tell."""
    included = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "X"}}]}
    """,
    )
    inline = App(
        {
            "id": "root",
            "widget": "Column",
            "children": [
                {"id": "r", "widget": "ListItem", "text": "X", "style": {"width": "expand"}}
            ],
        },
        theme=Theme(dark=True),
    )
    inline.mount()
    inline.update()
    assert included.root.find("r").text == inline.root.find("r").text
    assert included.root.find("r").size == inline.root.find("r").size


def test_overlays_can_be_included(views) -> None:
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: []}
        overlays:
          - {id: dlg, source: card.yaml, with: {title: "Confirm"}}
    """,
    )
    assert app.overlays.find("dlg") is not None
    assert app.overlays.find("dlg.heading").text == "Confirm"


def test_fragments_nest(views) -> None:
    (views / "outer.yaml").write_text(
        textwrap.dedent("""
        params: [name]
        id: outer
        widget: Column
        children:
          - {id: inner, source: row.yaml, with: {label: "{{ name }}"}}
    """)
    )
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: o, source: outer.yaml, with: {name: "nested"}}]}
    """,
    )
    assert app.root.find("o.inner").text == "nested"


# --------------------------------------------------------------- parameters


def test_plain_parameter_becomes_static_text(views) -> None:
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "Static"}}]}
    """,
    )
    assert app.root.find("r").text == "Static"


def test_a_binding_passed_as_a_parameter_stays_reactive(views) -> None:
    """Textual substitution is what makes this compose: the fragment ends up
    holding the caller's template, not a snapshot of its value."""
    live = Signal("before")
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "{{ live.get() }}"}}]}
    """,
        live=live,
    )
    assert app.root.find("r").text == "before"
    live.set("after")
    assert app.root.find("r").text == "after"


def test_missing_parameter_is_reported(views) -> None:
    with pytest.raises(SpecError, match="missing parameter"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: r, source: row.yaml}]}
        """,
        )


def test_unknown_parameter_is_reported(views) -> None:
    """Catches a typo'd parameter name rather than ignoring it."""
    with pytest.raises(SpecError, match="unknown parameter"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: r, source: row.yaml, with: {label: a, labl: b}}]}
        """,
        )


def test_call_site_may_not_carry_other_keys(views) -> None:
    """Parameters are the interface; merging would need murky precedence rules."""
    with pytest.raises(SpecError, match="only `id:` and `with:`"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: r, source: row.yaml, with: {label: a}, style: {width: 10}}]}
        """,
        )


# ------------------------------------------------------------- id namespacing


def test_the_same_fragment_included_twice_does_not_collide(views) -> None:
    """Reconciliation matches on (id, widget); duplicates would break state."""
    app = app_for(
        views,
        """
        root:
          id: root
          widget: Column
          children:
            - {id: a, source: card.yaml, with: {title: "A"}}
            - {id: b, source: card.yaml, with: {title: "B"}}
    """,
    )
    ids = [e.id for e in app.root.walk_elements()]
    assert len(ids) == len(set(ids))
    assert app.root.find("a.heading").text == "A"
    assert app.root.find("b.heading").text == "B"


def test_call_site_id_names_the_fragment_root(views) -> None:
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: mycard, source: card.yaml, with: {title: "T"}}]}
    """,
    )
    assert app.root.find("mycard") is not None
    assert app.root.find("card") is None, "the fragment's own root id leaked"


def test_state_survives_a_reload_of_an_included_tree(views) -> None:
    path = write(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: a, source: card.yaml, with: {title: "A"}}]}
    """,
    )
    app = App(path, theme=Theme(dark=True))
    app.mount()
    app.update()
    card = app.root.find("a")
    card.state.data["keep"] = "yes"
    app.reload(path)
    assert app.root.find("a") is card
    assert app.root.find("a").state.data["keep"] == "yes"


# ----------------------------------------------------------------- failures


def test_cycles_are_reported_with_the_chain(views) -> None:
    (views / "a.yaml").write_text("id: a\nwidget: Column\nchildren: [{id: b, source: b.yaml}]")
    (views / "b.yaml").write_text("id: b\nwidget: Column\nchildren: [{id: c, source: a.yaml}]")
    with pytest.raises(SpecError, match="include cycle"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [{id: x, source: a.yaml}]}
        """,
        )


def test_includes_may_not_escape_the_view_directory(views) -> None:
    """View files are untrusted input."""
    with pytest.raises(SpecError, match="outside the view directory"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: x, source: ../../../etc/passwd}]}
        """,
        )


def test_missing_file_is_reported(views) -> None:
    with pytest.raises(SpecError, match="not found"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: x, source: nope.yaml, with: {}}]}
        """,
        )


def test_a_fragment_must_be_a_mapping(views) -> None:
    (views / "list.yaml").write_text("- one\n- two\n")
    with pytest.raises(SpecError, match="must be a mapping"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: x, source: list.yaml, with: {}}]}
        """,
        )


def test_validation_errors_name_the_entry_file(views) -> None:
    (views / "bad.yaml").write_text("id: b\nwidget: Card\nstyle: {background: not_a_token}\n")
    with pytest.raises(SpecError, match="unknown MD3 token"):
        app_for(
            views,
            """
            root: {id: root, widget: Column, children: [
              {id: x, source: bad.yaml, with: {}}]}
        """,
        )


# ---------------------------------------------------------------- hot reload


def test_every_included_file_is_tracked(views) -> None:
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "x"}},
          {id: c, source: card.yaml, with: {title: "y"}}]}
    """,
    )
    assert {p.name for p in app.sources} == {"view.yaml", "row.yaml", "card.yaml"}


def test_hot_reload_watches_the_whole_graph(views) -> None:
    """Editing a fragment must reload the view, or `source:` silently breaks
    the framework's best feature."""
    path = write(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "before"}}]}
    """,
    )
    app = App(path, theme=Theme(dark=True))
    app.mount()
    app.update()
    assert app.root.find("r").text == "before"

    reloader = app.watch()
    try:
        assert {p.name for p in reloader.paths} == {"view.yaml", "row.yaml"}
        time.sleep(0.3)
        # Edit the FRAGMENT, not the entry file.
        (views / "row.yaml").write_text(
            'params: [label]\nid: item\nwidget: ListItem\ntext: "{{ label }}!"\n'
            "style: {width: expand}\n"
        )
        end = time.monotonic() + 5.0
        while time.monotonic() < end:
            if app.poll_reload():
                break
            time.sleep(0.05)
    finally:
        app.unwatch()
    assert app.root.find("r").text == "before!"


def test_dict_views_have_no_sources() -> None:
    app = App({"id": "r", "widget": "Column"}, theme=Theme(dark=True))
    assert app.sources == set()


def test_load_view_reports_sources(views) -> None:
    path = write(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: r, source: row.yaml, with: {label: "x"}}]}
    """,
    )
    seen: set = set()
    load_view(path, sources=seen)
    assert {p.name for p in seen} == {"view.yaml", "row.yaml"}


def test_a_view_without_includes_still_works(views) -> None:
    app = app_for(
        views,
        """
        root: {id: root, widget: Column, children: [
          {id: t, widget: Text, text: "plain"}]}
    """,
    )
    assert app.root.find("t").text == "plain"
