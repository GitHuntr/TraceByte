"""Shared presentation primitives for the FileCarveLab pages.

Every page is assembled from the same building blocks, so the dashboard reads
as one product instead of six different screens:

* :func:`page_header` - title plus lead line,
* :func:`section` - a bordered card with a heading,
* :func:`kpi_row` - a row of bordered metric cards,
* :func:`status_badge` - the colour language of the evidence states,
* :func:`empty_state` - what a screen shows when it has nothing to show yet.

Only native Streamlit elements are used: the look of the application is
controlled by ``.streamlit/config.toml``, not by custom CSS.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass

import streamlit as st

#: Evidence state -> (Material icon, badge colour).
STATUS_BADGE: dict[str, tuple[str, str]] = {
    "MATCH": ("check_circle", "green"),
    "MISMATCH": ("error", "red"),
    "MISSING": ("help", "orange"),
    "UNREGISTERED": ("warning", "yellow"),
    "COMPLETE": ("check_circle", "green"),
    "NOT STARTED": ("schedule", "gray"),
}

#: Condition -> Material icon, used in the pipeline and the result cards.
CONDITION_ICON: dict[str, str] = {
    "contiguous": "view_stream",
    "fragmented": "call_split",
    "overwritten": "content_cut",
}


@dataclass(frozen=True)
class Kpi:
    """One metric card in a KPI row."""

    label: str
    value: str | int | float
    delta: str | None = None
    help: str | None = None


def page_header(title: str, subtitle: str, icon: str | None = None) -> None:
    """Render the title and the lead line of a page.

    The icon is a Material Symbol name (``"dashboard"``); it is rendered in
    front of the title.
    """
    st.title(f":material/{icon}: {title}" if icon else title)
    st.markdown(subtitle)


@contextmanager
def section(
    title: str,
    icon: str | None = None,
    caption: str | None = None,
) -> Iterator[st.container]:
    """Open a bordered card with a heading and hand the container to the caller."""
    with st.container(border=True) as card:
        heading = f":material/{icon}: {title}" if icon else title
        st.markdown(f"#### {heading}")
        if caption:
            st.caption(caption)
        yield card


def kpi_row(items: Sequence[Kpi]) -> None:
    """Render a responsive row of bordered metric cards."""
    if not items:
        return
    with st.container(horizontal=True):
        for item in items:
            st.metric(
                item.label,
                item.value,
                delta=item.delta,
                help=item.help,
                border=True,
            )


def status_badge(status: str) -> None:
    """Render the colour language of an evidence state as a badge."""
    icon, colour = STATUS_BADGE.get(status.strip().upper(), ("info", "gray"))
    st.badge(status, icon=f":material/{icon}:", color=colour)


def status_cell(status: str) -> str:
    """Return the badge markup of an evidence state (for markdown cells)."""
    icon, colour = STATUS_BADGE.get(status.strip().upper(), ("info", "gray"))
    return f":{colour}-badge[{status}] :material/{icon}:"


def empty_state(icon: str, title: str, description: str) -> None:
    """Render the placeholder of a screen that has no data yet."""
    with st.container(border=True, horizontal_alignment="center"):
        st.markdown(f"#### :material/{icon}: {title}")
        st.caption(description)


def notice(
    body: str,
    kind: str = "info",
    icon: str | None = None,
) -> None:
    """Render a callout with a Material icon."""
    icons = {
        "info": "info",
        "success": "check_circle",
        "warning": "warning",
        "error": "error",
    }
    getter = getattr(st, kind)
    getter(body, icon=f":material/{icon or icons.get(kind, 'info')}:")


def percent(value: float, digits: int = 0) -> str:
    """Format a 0-1 ratio as a percentage string."""
    return f"{value * 100:.{digits}f}%"


def pipeline_step(icon: str, name: str, description: str) -> None:
    """Render one step of the pipeline as a small card."""
    with st.container(border=True, width="content"):
        st.markdown(f":material/{icon}: **{name}**")
        st.caption(description)
