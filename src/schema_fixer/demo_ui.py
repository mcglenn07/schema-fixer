"""Gradio presentation and event wiring for the package's demo workflow."""

import os
from functools import partial
from html import escape

# Set before importing Gradio so neither construction nor launch sends telemetry.
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

import gradio as gr

from schema_fixer.approval import ChecksFailed
from schema_fixer.demo import (
    MAX_UPLOAD_BYTES,
    ROOT,
    SAMPLES,
    SCHEMAS,
    DemoSession,
    DemoWorkflow,
    available_providers,
    cleanup_session,
    invalidate,
)
from schema_fixer.display import MAPPING_HEADERS, mapping_rows
from schema_fixer.io import InputError
from schema_fixer.providers import ProviderError

FINDING_HEADERS = ["Issue", "Target", "Source", "Data rows", "Details"]
CHECK_HEADERS = ["Level", "Target", "Source", "Data row", "Check", "Details"]
WELCOME = "**Ready.** Load a sample or upload a file, then inspect it."
CSS = """
.gradio-container { width: 100% !important; min-width: 0 !important; max-width: 1440px !important; margin: auto; }
#workflow, #review { min-width: 0 !important; max-width: 100%; }
.review-table { min-width: 0 !important; max-width: 100%; overflow-x: auto; }
.review-table table { font-family: inherit; }
#hero { padding: 22px 0 16px; }
#hero .eyebrow { color: #14756b; font: 600 12px ui-monospace, monospace; letter-spacing: .15em; }
#hero h1 { font-size: 38px; letter-spacing: -.045em; margin: 8px 0; }
#hero p { font-size: 16px; color: var(--body-text-color-subdued); margin: 4px 0; }
#status { border-left: 4px solid #168579; padding: 10px 16px; background: var(--block-background-fill); border-radius: 6px; }
#inputs { background: var(--block-background-fill); padding: 18px; border-radius: 12px; }
.dark #hero .eyebrow { color: #7bdcc0; }
@media (max-width: 600px) {
  #workflow { flex-direction: column !important; }
  #inputs, #review { min-width: 0 !important; width: 100%; flex: none !important; }
  #hero h1 { font-size: 32px; }
}
footer { display: none !important; }
"""


def check_rows(checks):
    return [
        [
            issue.severity,
            issue.field or "",
            issue.source or "",
            str(issue.row or ""),
            issue.code,
            issue.message,
        ]
        for issue in checks.issues
    ]


def finding_rows(report):
    # Deliberately omit finding.samples: only quarantine downloads contain original bad values.
    return [
        [
            finding.code,
            finding.field or "",
            finding.source or "",
            ", ".join(map(str, finding.rows)),
            finding.message,
        ]
        for finding in report.findings
    ]


def error_status(exc):
    if isinstance(exc, ChecksFailed):
        return "**Blocked.** The mapping failed code checks. Review the findings; no clean or quarantine output was written."
    if isinstance(exc, (InputError, ProviderError)):
        return f"**Could not continue.** {escape(str(exc))}"
    return "**Could not continue.** Unable to process the demo files. Reload the file and try again."


class DemoCallbacks:
    """Small UI adapters. Every data operation delegates to DemoWorkflow."""

    def __init__(self, workflow):
        self.workflow = workflow

    def reset(self, session):
        invalidate(session)
        return (
            session,
            WELCOME,
            [],
            [],
            [],
            gr.update(interactive=False),
            gr.update(value=None, interactive=False),
            gr.update(value=None, interactive=False),
        )

    def inspect(self, file, schema, provider, session):
        cleared = self.reset(session)
        # Clear stale approval/downloads before any slow provider request.
        yield cleared
        findings = []
        try:
            review = self.workflow.inspect(file, schema, provider, session)
            findings = finding_rows(review.inspection)
            yield (
                session,
                f"**Inspected {len(review.frame)} rows.** Preparing a mapping with {provider}…",
                findings,
                *cleared[3:],
            )
            proposal = self.workflow.propose(session)
            checks = proposal.checks
            status = (
                f"**Ready for review.** {checks.rows_checked} sample rows checked; "
                f"{len(checks.quarantine_rows)} would be quarantined. Review the mapping, then approve."
                if checks.passed
                else "**Flagged draft.** Fix the source file or review/edit the mapping in the CLI. Approval is disabled."
            )
            if not checks.passed and provider == "baseline":
                status += " Header matching cannot join columns or match by meaning" + (
                    "; try the OpenAI provider."
                    if "openai" in available_providers()
                    else "."
                )
            yield (
                session,
                status,
                findings,
                mapping_rows(proposal.mapping, checks),
                check_rows(checks),
                gr.update(interactive=checks.passed),
                *cleared[6:],
            )
        except (InputError, ProviderError, OSError, UnicodeError) as exc:
            invalidate(session)
            yield (session, error_status(exc), findings, [], [], *cleared[5:])

    def approve(self, file, schema, provider, session):
        try:
            report = self.workflow.approve(file, schema, provider, session)
            checks = report.checks
            return (
                session,
                (
                    f"**Applied.** {checks.rows_checked} rows checked · {checks.valid_rows} clean · "
                    f"{len(checks.quarantine_rows)} quarantined. Download your files below."
                ),
                gr.skip(),
                gr.skip(),
                check_rows(checks),
                gr.update(interactive=False),
                gr.update(value=report.clean_file, interactive=True),
                gr.update(value=report.quarantine_file, interactive=True),
            )
        except (InputError, ProviderError, OSError, UnicodeError) as exc:
            invalidate(session)
            return (
                session,
                error_status(exc),
                gr.skip(),
                gr.skip(),
                check_rows(exc.checks) if isinstance(exc, ChecksFailed) else [],
                gr.update(interactive=False),
                gr.update(value=None, interactive=False),
                gr.update(value=None, interactive=False),
            )


def build_demo(root=ROOT):
    workflow = DemoWorkflow(root)
    callbacks = DemoCallbacks(workflow)
    with gr.Blocks(
        title="Schema Fixer", analytics_enabled=False, delete_cache=(60, 3600)
    ) as demo:
        session = gr.State(
            DemoSession(), time_to_live=3600, delete_callback=cleanup_session
        )
        gr.HTML("""<div id="hero"><div class="eyebrow">LOCAL DATA REPAIR</div>
            <h1>Schema Fixer</h1><p>Review a mapping. Keep the good rows.</p></div>""")
        status = gr.Markdown(WELCOME, elem_id="status")
        with gr.Row(elem_id="workflow"):
            with gr.Column(scale=1, min_width=280, elem_id="inputs"):
                gr.Markdown(
                    "### 1 · Choose your data\nCSV or a JSON array of flat objects. Up to 10 MiB."
                )
                upload = gr.File(
                    label="Incoming file", file_types=[".csv", ".json"], type="filepath"
                )
                schema = gr.Dropdown(
                    list(SCHEMAS), value="Customers", label="Target schema"
                )
                provider = gr.Dropdown(
                    available_providers(), value="baseline", label="Provider"
                )
                gr.Markdown(
                    "Baseline matches headers locally, with no API key. OpenAI, when selected, receives the schema and masked column profiles."
                )
                inspect_button = gr.Button("Inspect & propose", variant="primary")
                gr.Markdown(
                    "#### Try a sample\nSynthetic files. Each button loads a file and its target schema."
                )
                for index, (label, _, _) in enumerate(SAMPLES):
                    gr.Button(label, size="sm").click(
                        partial(workflow.sample, index),
                        outputs=[upload, schema],
                        api_name=False,
                        queue=False,
                    )
            with gr.Column(scale=3, min_width=400, elem_id="review"):
                gr.Markdown("### 2 · Review the changes")
                findings = gr.Dataframe(
                    headers=FINDING_HEADERS,
                    datatype="str",
                    value=[],
                    interactive=False,
                    label="Mismatch report",
                    elem_classes="review-table",
                    column_widths=[130, 140, 140, 85, 260],
                    max_height=230,
                    wrap=True,
                )
                mapping = gr.Dataframe(
                    headers=MAPPING_HEADERS,
                    datatype="str",
                    value=[],
                    interactive=False,
                    label="Proposed mapping",
                    elem_classes="review-table",
                    column_widths=[120, 130, 150, 130, 115, 240],
                    max_height=350,
                    wrap=True,
                )
                with gr.Accordion("Code checks and row reasons", open=False):
                    checks = gr.Dataframe(
                        headers=CHECK_HEADERS,
                        datatype="str",
                        value=[],
                        interactive=False,
                        label="Checks",
                        elem_classes="review-table",
                        column_widths=[90, 140, 140, 85, 130, 280],
                        wrap=True,
                    )
                gr.Markdown(
                    "### 3 · Approve & download\nApproval checks every row. Invalid rows go to quarantine; original invalid values appear only in that download."
                )
                approve_button = gr.Button(
                    "Approve & apply", interactive=False, variant="primary"
                )
                with gr.Row():
                    clean = gr.DownloadButton("Download clean.csv", interactive=False)
                    quarantine = gr.DownloadButton(
                        "Download quarantine.csv", interactive=False
                    )
        gr.Markdown(
            "Local demo · Files expire after the session · For mapping edits and saved reuse, use the CLI."
        )
        outputs = [
            session,
            status,
            findings,
            mapping,
            checks,
            approve_button,
            clean,
            quarantine,
        ]
        event_options = {
            "concurrency_id": "review",
            "concurrency_limit": 1,
            "api_name": False,
        }
        for component in (upload, schema, provider):
            component.change(callbacks.reset, session, outputs, **event_options)
        inspect_button.click(
            callbacks.inspect,
            [upload, schema, provider, session],
            outputs,
            **event_options,
        )
        approve_button.click(
            callbacks.approve,
            [upload, schema, provider, session],
            outputs,
            **event_options,
        )
    return demo.queue(default_concurrency_limit=1)


def launch_demo(demo):
    return demo.launch(
        server_name="127.0.0.1",
        share=False,
        show_error=False,
        max_file_size=MAX_UPLOAD_BYTES,
        enable_monitoring=False,
        footer_links=[],
        theme=gr.themes.Soft(
            primary_hue="teal",
            neutral_hue="slate",
            font=["system-ui"],
            font_mono=["ui-monospace"],
        ),
        css=CSS,
    )
