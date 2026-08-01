"""Golden-fixture evaluation harness (docs/04-llm-pipeline.md §10): runs the
real triage/analysis prompt-building code (triage.py/analyze.py, unmodified)
against a frozen fixture set and reports drift against expected outcomes.
`make eval` runs this against the live API — run it before changing any
prompt, and bump the prompt version string on any change.

Grading per §10: tolerant (±0.15) on magnitude/confidence, strict on
relevant/direction/topic matching. Uses budget/spend-ledger purposes
'eval_triage'/'eval_analysis' so eval runs are visible in the spend ledger
like any other call, and cycle_id=None (an eval run isn't a digest cycle).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Connection

from newswatch_worker.llm import analyze, client, pm_estimate, triage
from newswatch_worker.llm.watch_context import build_watch_context, short_id_map

logger = logging.getLogger(__name__)

FIXTURES_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_fixtures.json"
PM_FIXTURES_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pm_fixtures.json"
TOLERANCE = 0.15


def load_fixtures() -> list[dict]:
    data = json.loads(FIXTURES_PATH.read_text())
    return data["fixtures"]


def load_pm_fixtures() -> list[dict]:
    data = json.loads(PM_FIXTURES_PATH.read_text())
    return data["fixtures"]


@dataclass
class FixtureReport:
    fixture_id: str
    triage_pass: bool
    triage_notes: list[str] = field(default_factory=list)
    analysis_pass: bool | None = None
    analysis_notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.triage_pass and self.analysis_pass is not False


def _grade_triage(expected: dict, actual_relevant: bool, actual_topic_names: set[str]) -> tuple[bool, list[str]]:
    notes = []
    ok = True
    if actual_relevant != expected["relevant"]:
        ok = False
        notes.append(f"relevant: expected {expected['relevant']}, got {actual_relevant}")
    expected_topics = set(expected.get("matched_topic_names", []))
    if expected["relevant"] and actual_relevant and actual_topic_names != expected_topics:
        ok = False
        notes.append(f"matched_topic_names: expected {sorted(expected_topics)}, got {sorted(actual_topic_names)}")
    return ok, notes


def _grade_analysis(expected: dict, analysis, matched_names: set[str]) -> tuple[bool, list[str]]:
    notes = []
    ok = True
    if analysis.event_polarity != expected["event_polarity"]:
        ok = False
        notes.append(f"event_polarity: expected {expected['event_polarity']}, got {analysis.event_polarity}")
    if abs(analysis.magnitude - expected["magnitude"]) > TOLERANCE:
        ok = False
        notes.append(f"magnitude: expected {expected['magnitude']}+/-{TOLERANCE}, got {analysis.magnitude}")
    if abs(analysis.confidence - expected["confidence"]) > TOLERANCE:
        ok = False
        notes.append(f"confidence: expected {expected['confidence']}+/-{TOLERANCE}, got {analysis.confidence}")
    expected_topics = set(expected.get("matched_topic_names", []))
    if matched_names != expected_topics:
        ok = False
        notes.append(f"matched_topic_names: expected {sorted(expected_topics)}, got {sorted(matched_names)}")
    for exp_impact in expected.get("impacts", []):
        found = any(
            i.market == exp_impact["market"] and i.sector == exp_impact["sector"] and i.direction == exp_impact["direction"]
            for i in analysis.impacts
        )
        if not found:
            ok = False
            notes.append(f"missing expected impact: {exp_impact}")
    return ok, notes


def _render_eval_analysis_input(fixture: dict) -> str:
    inp = fixture["input"]
    return (
        f"story_key: eval-{fixture['id']}\n\n"
        "## Primary item\n"
        f"title: {inp['title']}\n"
        f"source: {inp['source']}\n"
        f"published_at: {inp.get('published_at', 'unknown')}\n"
        f"body: {inp.get('body_excerpt') or inp['summary']}"
    )


def run_eval(conn: Connection) -> list[FixtureReport]:
    fixtures = load_fixtures()
    llm_settings = client.get_llm_settings(conn)
    watch_context, topics = build_watch_context(conn)
    id_map = short_id_map(topics)
    name_by_full_id = {t.id: t.name for t in topics}

    triage_model, triage_reasoning = llm_settings.tier("triage")
    analysis_model, analysis_reasoning = llm_settings.tier("analysis")

    reports: list[FixtureReport] = []
    for fx in fixtures:
        input_item = triage.TriageInputItem(
            id=fx["id"],
            source_name=fx["input"]["source"],
            title=fx["input"]["title"],
            summary=fx["input"]["summary"],
            published_at=fx["input"].get("published_at"),
            provider_tags=None,
        )
        triage_system = triage.SYSTEM_PROMPT_TEMPLATE.format(watch_context=watch_context, already_assigned="(none yet)")
        triage_call = client.call_structured(
            conn,
            cycle_id=None,
            purpose="eval_triage",
            model=triage_model,
            reasoning=triage_reasoning,
            output_model=triage.TriageResult,
            system=triage_system,
            user_content=triage.render_batch([input_item]),
            temperature=0.0,
        )
        if triage_call is None or not triage_call.parsed.items:
            reports.append(
                FixtureReport(fixture_id=fx["id"], triage_pass=False, triage_notes=["triage call failed or returned no items"])
            )
            continue

        item_result = triage_call.parsed.items[0]
        actual_topic_names = {name_by_full_id[id_map[s]] for s in item_result.matched_topic_ids if s in id_map}
        triage_ok, triage_notes = _grade_triage(fx["expected_triage"], item_result.relevant, actual_topic_names)
        report = FixtureReport(fixture_id=fx["id"], triage_pass=triage_ok, triage_notes=triage_notes)

        if "expected_analysis" not in fx or not item_result.relevant:
            reports.append(report)
            continue

        resolved_topic_ids = frozenset(id_map[s] for s in item_result.matched_topic_ids if s in id_map)
        by_topic = analyze.load_mapping_rows_for_topics(conn, resolved_topic_ids)
        analysis_system = analyze.SYSTEM_PROMPT_TEMPLATE.format(
            watch_context=watch_context, mapping_rows=analyze.render_mapping_rows(by_topic)
        )
        analysis_call = client.call_structured(
            conn,
            cycle_id=None,
            purpose="eval_analysis",
            model=analysis_model,
            reasoning=analysis_reasoning,
            output_model=analyze.AnalysisResult,
            system=analysis_system,
            user_content=_render_eval_analysis_input(fx),
            temperature=0.0,
        )
        if analysis_call is None:
            report.analysis_pass = False
            report.analysis_notes = ["analysis call failed (no valid JSON after repair retry)"]
            reports.append(report)
            continue

        analysis = analysis_call.parsed
        analyze.strip_hallucinated_tickers(analysis, by_topic)
        matched_names = {
            name_by_full_id[id_map[mt.topic_id]] for mt in analysis.matched_topics if id_map.get(mt.topic_id) in name_by_full_id
        }
        analysis_ok, analysis_notes = _grade_analysis(fx["expected_analysis"], analysis, matched_names)
        report.analysis_pass = analysis_ok
        report.analysis_notes = analysis_notes
        reports.append(report)

    return reports


def print_drift_report(reports: list[FixtureReport]) -> bool:
    """Returns True iff every fixture passed."""
    for r in reports:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.fixture_id}")
        for note in r.triage_notes:
            print(f"    triage:   {note}")
        for note in r.analysis_notes:
            print(f"    analysis: {note}")
    passed = sum(1 for r in reports if r.passed)
    print(f"\n{passed}/{len(reports)} fixtures passed.")
    return passed == len(reports)


@dataclass
class PmFixtureReport:
    fixture_id: str
    passed: bool
    notes: list[str] = field(default_factory=list)


def _grade_pm_estimate(expected: dict, actual: pm_estimate.PmEstimate) -> tuple[bool, list[str]]:
    notes = []
    ok = True
    if actual.skip != expected["skip"]:
        ok = False
        notes.append(f"skip: expected {expected['skip']}, got {actual.skip}")
    if expected["skip"]:
        return ok, notes
    if "est_probability" in expected and abs(actual.est_probability - expected["est_probability"]) > TOLERANCE:
        ok = False
        notes.append(
            f"est_probability: expected {expected['est_probability']}+/-{TOLERANCE}, got {actual.est_probability}"
        )
    if "confidence_min" in expected and actual.confidence < expected["confidence_min"]:
        ok = False
        notes.append(f"confidence: expected >= {expected['confidence_min']}, got {actual.confidence}")
    if "confidence_max" in expected and actual.confidence > expected["confidence_max"]:
        ok = False
        notes.append(f"confidence: expected <= {expected['confidence_max']}, got {actual.confidence}")
    return ok, notes


def run_pm_eval(conn: Connection) -> list[PmFixtureReport]:
    fixtures = load_pm_fixtures()
    llm_settings = client.get_llm_settings(conn)
    model, reasoning = llm_settings.tier("pm_estimate")
    today = "2026-08-01 (Saturday)"  # frozen so fixtures are reproducible regardless of run date

    reports: list[PmFixtureReport] = []
    for fx in fixtures:
        inp = fx["input"]
        market = pm_estimate.MarketInput(
            market_id=f"eval-{fx['id']}",
            question=inp["question"],
            market_price=inp["market_price"],
            end_date=inp.get("end_date"),
            category=inp.get("category"),
        )
        call_result = pm_estimate.estimate_probability(
            conn,
            cycle_id=None,
            market=market,
            storylines=inp.get("related_storylines", []),
            model=model,
            reasoning=reasoning,
            today=today,
        )
        if call_result is None:
            reports.append(PmFixtureReport(fixture_id=fx["id"], passed=False, notes=["pm-estimate call failed or returned no result"]))
            continue
        ok, notes = _grade_pm_estimate(fx["expected"], call_result.parsed)
        reports.append(PmFixtureReport(fixture_id=fx["id"], passed=ok, notes=notes))

    return reports


def print_pm_drift_report(reports: list[PmFixtureReport]) -> bool:
    """Returns True iff every PM fixture passed."""
    for r in reports:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.fixture_id}")
        for note in r.notes:
            print(f"    pm_estimate: {note}")
    passed = sum(1 for r in reports if r.passed)
    print(f"\n{passed}/{len(reports)} PM fixtures passed.")
    return passed == len(reports)
