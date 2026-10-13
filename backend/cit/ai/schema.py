"""Research report output contract and post-generation validation.

The model must return JSON matching REPORT_JSON_SCHEMA (enforced by the API's
structured outputs), which is then validated again with Pydantic and checked
against the evidence bundle:
  * every cited evidence id must exist in the bundle;
  * every claim must cite at least one evidence id;
  * every material number in the prose must appear in the evidence
    (no fabricated figures; the model is told not to compute new numbers).
Failing reports are stored as `rejected_schema` with the reasons.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

PROMPT_VERSION = "research-v1"

Priority = Literal["high", "medium", "low", "avoid", "insufficient_data"]
Confidence = Literal["low", "medium", "high"]


class Claim(BaseModel):
    statement: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class Section(BaseModel):
    assessment: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=15)
    confidence: Confidence


class ResearchReport(BaseModel):
    executive_summary: str = Field(min_length=1, max_length=1500)
    project_description: str = Field(min_length=1, max_length=1500)
    evidence_for: list[Claim] = Field(max_length=10)
    evidence_against: list[Claim] = Field(max_length=10)
    tokenomics: Section
    contract_risks: Section
    liquidity_risks: Section
    community_quality: Section
    insider_concentration: Section
    catalysts: Section
    unknowns: list[str] = Field(max_length=15)
    research_priority: Priority
    priority_rationale: str = Field(min_length=1, max_length=800)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_ids = {"type": "array", "items": {"type": "string"}}
_claim = _obj({"statement": {"type": "string"}, "evidence_ids": _ids})
_section = _obj(
    {
        "assessment": {"type": "string"},
        "evidence_ids": _ids,
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    }
)

REPORT_JSON_SCHEMA: dict[str, Any] = _obj(
    {
        "executive_summary": {"type": "string"},
        "project_description": {"type": "string"},
        "evidence_for": {"type": "array", "items": _claim},
        "evidence_against": {"type": "array", "items": _claim},
        "tokenomics": _section,
        "contract_risks": _section,
        "liquidity_risks": _section,
        "community_quality": _section,
        "insider_concentration": _section,
        "catalysts": _section,
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "research_priority": {"type": "string", "enum": ["high", "medium", "low", "avoid", "insufficient_data"]},
        "priority_rationale": {"type": "string"},
    }
)


# ---------------------------------------------------------------------------
# Evidence checks
# ---------------------------------------------------------------------------

NUM_RE = re.compile(r"(?<![A-Za-z0-9_])\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kKmMbB](?![a-zA-Z]))?")
# Numbers that are vocabulary, not data: time windows, small counts, top-N.
ALLOWED_PLAIN = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15, 24, 30, 48, 72, 90, 100}
SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9}


def evidence_numbers(obj: Any, out: set[float] | None = None) -> set[float]:
    out = out if out is not None else set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)) and math.isfinite(obj):
        out.add(float(obj))
    elif isinstance(obj, str):
        # Numbers inside evidence strings (e.g. untrusted excerpts) do NOT count as evidence.
        pass
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k != "untrusted_text":
                evidence_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            evidence_numbers(v, out)
    return out


def numbers_in(text: str) -> list[float]:
    vals = []
    for m in NUM_RE.finditer(text):
        raw, suf = m.group(1).replace(",", ""), (m.group(2) or "").lower()
        try:
            v = float(raw) * SUFFIX.get(suf, 1)
        except ValueError:
            continue
        if 1900 <= v <= 2100 and not suf and "." not in raw:  # years
            continue
        vals.append(v)
    return vals


def _matches(v: float, known: set[float]) -> bool:
    if v in ALLOWED_PLAIN:
        return True
    for k in known:
        if k == 0:
            if v == 0:
                return True
            continue
        if abs(v - k) / abs(k) <= 0.02:  # rounding tolerance (e.g. $25.5K vs 25512.3)
            return True
    return False


def all_text(report: ResearchReport) -> list[str]:
    texts = [report.executive_summary, report.project_description, report.priority_rationale, *report.unknowns]
    texts += [c.statement for c in report.evidence_for + report.evidence_against]
    for s in (
        report.tokenomics,
        report.contract_risks,
        report.liquidity_risks,
        report.community_quality,
        report.insider_concentration,
        report.catalysts,
    ):
        texts.append(s.assessment)
    return texts


def cited_ids(report: ResearchReport) -> set[str]:
    ids = {i for c in report.evidence_for + report.evidence_against for i in c.evidence_ids}
    for s in (
        report.tokenomics,
        report.contract_risks,
        report.liquidity_risks,
        report.community_quality,
        report.insider_concentration,
        report.catalysts,
    ):
        ids.update(s.evidence_ids)
    return ids


def validate_report(raw: Any, bundle: dict[str, Any]) -> tuple[ResearchReport | None, list[str]]:
    """Return (report, problems). A report with problems must not be shown as valid."""
    try:
        report = ResearchReport.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()[:10]]
    problems: list[str] = []
    known_ids = {e["id"] for e in bundle.get("evidence", [])}
    unknown = sorted(cited_ids(report) - known_ids)
    if unknown:
        problems.append(f"cites evidence ids that do not exist: {unknown[:10]}")
    known_nums = evidence_numbers(bundle)
    fabricated = sorted({v for t in all_text(report) for v in numbers_in(t) if not _matches(v, known_nums)})
    if fabricated:
        problems.append(f"numbers not present in evidence: {fabricated[:10]}")
    return report, problems
