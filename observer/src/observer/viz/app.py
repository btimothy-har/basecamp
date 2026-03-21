# ruff: noqa: PLC0415
import marimo
import plotly.graph_objects as go

__generated_with = "0.19.11"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    from observer.viz import queries

    scopes = queries.get_project_scopes()
    scope_options: dict[str, tuple[int, int | None] | None] = {"All": None}
    for s in scopes:
        scope_options[s["project_name"]] = (s["project_id"], None)
        for wt in s["worktrees"]:
            scope_options[f"{s['project_name']}/{wt['label']}"] = (
                s["project_id"],
                wt["id"],
            )
    scope_dropdown = mo.ui.dropdown(
        options=scope_options,
        value=None,
        label="Scope",
    )

    return queries, scope_dropdown


@app.cell
def _(mo, queries, scope_dropdown):
    project_id, worktree_id = scope_dropdown.value or (None, None)

    transcripts = queries.get_transcripts(
        project_id=project_id,
        worktree_id=worktree_id,
    )
    transcript_options = {"All transcripts": None} | {
        (t["title"] or t["session_id"][:12]) + f" ({t['event_count']} events)": t["id"] for t in transcripts
    }
    transcript_dropdown = mo.ui.dropdown(
        options=transcript_options,
        value=None,
        label="Transcript",
    )

    return (transcript_dropdown,)


@app.cell
def _(mo, queries, scope_dropdown, transcript_dropdown):
    _pid, _wid = scope_dropdown.value or (None, None)
    stats = queries.get_pipeline_stats(
        transcript_id=transcript_dropdown.value,
        project_id=_pid,
        worktree_id=_wid,
    )

    mo.sidebar(
        [
            mo.md("# Observer"),
            mo.md(
                f"**Events**: {stats['total_events']}\n\n"
                f"- {stats['processed']} processed\n"
                f"- {stats['skipped']} skipped\n"
                f"- {stats['errors']} errors\n"
                f"- {stats['pending']} pending\n\n"
                f"**Extractions**: {stats['total_extractions']}"
            ),
        ]
    )

    return (stats,)


@app.cell
def _(mo, queries, scope_dropdown, transcript_dropdown):
    _tid = transcript_dropdown.value
    _pid, _wid = scope_dropdown.value or (None, None)

    status_counts = queries.get_processing_status_counts(
        transcript_id=_tid,
        project_id=_pid,
        worktree_id=_wid,
    )
    section_counts = queries.get_section_type_counts(
        transcript_id=_tid,
        project_id=_pid,
        worktree_id=_wid,
    )

    def _make_bar(data: list[dict], key: str, title: str) -> go.Figure:
        if not data:
            return go.Figure().update_layout(title=title)
        fig = go.Figure(
            go.Bar(
                x=[str(d[key]) for d in data],
                y=[d["count"] for d in data],
            )
        )
        fig.update_layout(title=title, height=300, margin={"t": 40, "b": 30, "l": 40, "r": 20})
        return fig

    pipeline_tab = mo.vstack(
        [
            mo.md("## Pipeline Overview"),
            _make_bar(status_counts, "status", "Processing Status"),
            _make_bar(section_counts, "type", "Section Types"),
        ]
    )

    return (pipeline_tab,)


@app.cell
def _(mo, queries, scope_dropdown, transcript_dropdown):
    _tid = transcript_dropdown.value
    _pid, _wid = scope_dropdown.value or (None, None)
    _extractions = queries.get_extractions(
        transcript_id=_tid,
        project_id=_pid,
        worktree_id=_wid,
    )

    _table_data = [
        {
            "id": e["id"],
            "type": str(e["type"]),
            "text": e["text"][:120] + ("..." if len(e["text"]) > 120 else ""),
            "created": e["created_at"],
        }
        for e in _extractions
    ]

    extraction_table = (
        mo.ui.table(
            data=_table_data,
            selection="single",
            page_size=20,
            label="Extractions",
        )
        if _table_data
        else None
    )

    return (extraction_table,)


@app.cell
def _(extraction_table, mo, queries):
    _detail = mo.md("*Select an extraction from the table to see details.*")

    if extraction_table is not None and extraction_table.value:
        _selected = extraction_table.value[0]
        _info = queries.get_extraction_detail(_selected["id"])
        if _info:
            _detail = mo.vstack(
                [
                    mo.md(f"### {str(_info['type']).upper()} (id={_info['id']})"),
                    mo.md("**Extracted Text**"),
                    mo.md(f"```\n{_info['text']}\n```"),
                ]
            )

    extraction_browser_tab = mo.vstack(
        [
            mo.md("## Extraction Browser"),
            extraction_table if extraction_table is not None else mo.md("*No extractions found.*"),
            mo.md("---"),
            _detail,
        ]
    )

    return (extraction_browser_tab,)


@app.cell
def _(mo, queries, transcript_dropdown):
    _tid = transcript_dropdown.value

    if _tid is not None:
        _events = queries.get_timeline_events(_tid)
        _status = {"pending": "pending", "processed": "ok", "skipped": "skip", "error": "ERR"}
        _rows = [
            {
                "time": item["timestamp"],
                "kind": item["kind"],
                "type": item.get("event_type", "") or str(item.get("section_type", "")),
                "status": _status.get(item.get("status", ""), item.get("status", "")),
                "detail": item.get("text", "")[:120] if item.get("text") else "",
            }
            for item in _events
        ]
        _content = mo.ui.table(data=_rows, page_size=50) if _rows else mo.md("*No events.*")
    else:
        _content = mo.md("*Select a transcript to view timeline.*")

    timeline_tab = mo.vstack([mo.md("## Timeline"), _content])

    return (timeline_tab,)


@app.cell
def _(
    extraction_browser_tab,
    mo,
    pipeline_tab,
    scope_dropdown,
    timeline_tab,
    transcript_dropdown,
):
    mo.vstack(
        [
            mo.hstack([scope_dropdown, transcript_dropdown], justify="start", gap=1),
            mo.Html("<hr style='margin: 1rem 0;'>"),
            mo.ui.tabs(
                {
                    "Pipeline": pipeline_tab,
                    "Extractions": extraction_browser_tab,
                    "Timeline": timeline_tab,
                }
            ),
        ]
    )
    return


if __name__ == "__main__":
    app.run()
