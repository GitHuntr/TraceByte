"""Experiment log page: the append-only provenance record.

Every action of the tool appends one JSON line to `logs/experiment_log.jsonl`.
The log is never rewritten, so it is the record that can be trusted when the
question is *what actually happened*.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

import src.paths as paths
from app.ui import Kpi, empty_state, kpi_row, notice, page_header, section
from src.experiment_log import ExperimentLog

page_header(
    "Experiment log",
    "An append-only JSON Lines record of every action: dataset initialisation, "
    "integrity checks and experiment runs. Nothing is ever rewritten, so the "
    "history of a workspace can always be reconstructed.",
    icon="description",
)

log = ExperimentLog(paths.EXPERIMENT_LOG_PATH, enabled=False)
events = log.read_events()

if not events:
    empty_state(
        "description",
        "The log is empty",
        "Run the dataset initialisation or a carving experiment to record the "
        "first event.",
    )
    st.stop()

frame = pd.DataFrame(
    [
        {
            "timestamp_utc": event.get("timestamp_utc", ""),
            "event": event.get("event", ""),
            "actor": event.get("actor", ""),
            "run_id": event.get("run_id", ""),
            "payload": event.get("payload", {}),
        }
        for event in events
    ]
)

event_types = sorted(frame["event"].unique())
actors = sorted(frame["actor"].unique())
runs = sorted({value for value in frame["run_id"] if value})

kpi_row(
    [
        Kpi("Events", len(frame), help="Records in the append-only log"),
        Kpi("Event types", len(event_types), help="Distinct kinds of recorded action"),
        Kpi("Runs", len(runs), help="Run identifiers that appear in the log"),
        Kpi("Last event", frame["timestamp_utc"].iloc[-1][:19].replace("T", " ")),
    ]
)

with section(
    "Filters",
    icon="filter_alt",
    caption="Narrow the log down to the actions you are interested in.",
):
    col_a, col_b = st.columns(2)
    with col_a:
        selected_types = st.multiselect(
            "Event type",
            options=event_types,
            default=event_types,
            help="Every recorded event type; deselect the ones you do not need.",
        )
    with col_b:
        selected_actors = st.multiselect(
            "Actor",
            options=actors,
            default=actors,
            help="The tool version that produced the event.",
        )

filtered = frame[
    frame["event"].isin(selected_types) & frame["actor"].isin(selected_actors)
]

with section(
    "Activity",
    icon="bar_chart",
    caption="How the recorded events are distributed.",
):
    if filtered.empty:
        st.info("No event matches the current filter.")
    else:
        counts = (
            filtered.groupby("event").size().rename("Events").reset_index()
        )
        st.bar_chart(counts, x="event", y="Events", horizontal=True)

with section(
    "Events",
    icon="list_alt",
    caption=f"{len(filtered)} of {len(frame)} events, newest first.",
):
    ordered = filtered.sort_values("timestamp_utc", ascending=False).reset_index(drop=True)
    ordered["timestamp"] = pd.to_datetime(ordered["timestamp_utc"], utc=True)

    st.dataframe(
        ordered[["timestamp", "event", "actor", "run_id", "payload"]],
        hide_index=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn(
                "Timestamp (UTC)", format="YYYY-MM-DD HH:mm:ss"
            ),
            "event": st.column_config.TextColumn("Event", pinned=True),
            "actor": st.column_config.TextColumn("Actor"),
            "run_id": st.column_config.TextColumn("Run"),
            "payload": st.column_config.JsonColumn("Payload"),
        },
    )

    st.download_button(
        "Download the log (JSON Lines)",
        data=paths.EXPERIMENT_LOG_PATH.read_text(encoding="utf-8")
        if paths.EXPERIMENT_LOG_PATH.exists()
        else "",
        file_name="experiment_log.jsonl",
        mime="application/x-ndjson",
        icon=":material/download:",
    )

with st.expander("Log format", icon=":material/code:"):
    st.markdown(
        "One JSON object per line, appended in the order the actions happened:"
    )
    st.code(
        json.dumps(
            {
                "actor": "filecarvelab.stage1",
                "event": "experiment_completed",
                "payload": {"condition": "contiguous", "run_id": "run-..."},
                "run_id": "d58890396780",
                "timestamp_utc": "2026-10-21T09:52:31Z",
                "tool_versions": {"python": "3.14.5", "streamlit": "1.60.0"},
            },
            indent=2,
        ),
        language="json",
    )
    notice(
        "The log is append-only by design: entries are never edited or removed, "
        "so a later baseline change can always be distinguished from the "
        "original measurement.",
        kind="info",
    )
