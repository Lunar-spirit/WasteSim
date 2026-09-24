"""Intent and entity extraction (design 5.8's pipeline step 1). Two paths:

  1. A real LLM call (Anthropic's tool-use / function-calling), used only
     when ANTHROPIC_API_KEY is configured.
  2. A deterministic keyword-and-regex matcher over the same fixed tool set,
     used whenever no key is configured OR the provider call fails for any
     reason (timeout, 5xx, network) — EXT-05 and T-57: "the feature still
     demonstrates without internet access... never an invented number".

Both paths return the same shape: (tool_name | None, arguments: dict). A
None tool_name means "ask a clarifying question, don't guess" (design's own
guardrail) — this module never invents a tool call it isn't confident in.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import settings

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")

TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "get_habitation_summary",
        "description": "Profile, status, active parameter version and GIS layers for the habitation this session is bound to.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_runs",
        "description": "List simulation runs for this habitation, with their labels and findings.",
        "input_schema": {"type": "object", "properties": {"run_type": {"type": "string", "enum": ["BASE", "SCENARIO", "SENSITIVITY", "OPTIMIZED"]}}},
    },
    {
        "name": "get_run_result",
        "description": "Yearly result values for one run, optionally one year and a chosen set of indicators.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "year_index": {"type": "integer"},
                "indicators": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "get_run_findings",
        "description": "The headline findings (e.g. landfill exhaustion year) for one run.",
        "input_schema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]},
    },
    {
        "name": "compare_runs",
        "description": "Aligned yearly series across 2-5 runs for a chosen set of indicators.",
        "input_schema": {
            "type": "object",
            "properties": {"run_ids": {"type": "array", "items": {"type": "string"}}, "indicators": {"type": "array", "items": {"type": "string"}}},
            "required": ["run_ids"],
        },
    },
    {
        "name": "get_budget",
        "description": "Budget totals (opex, capex, NPV) for one run.",
        "input_schema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"]},
    },
    {
        "name": "explain_difference",
        "description": "The indicators that diverge most between two runs, and the month they diverge most in.",
        "input_schema": {"type": "object", "properties": {"run_a": {"type": "string"}, "run_b": {"type": "string"}}, "required": ["run_a", "run_b"]},
    },
    {
        "name": "create_scenario_run",
        "description": "Start a calamity/scenario run against a base run (write).",
        "input_schema": {
            "type": "object",
            "properties": {"base_run_id": {"type": "string"}, "events": {"type": "array", "items": {"type": "object"}}},
            "required": ["base_run_id", "events"],
        },
    },
    {
        "name": "run_sensitivity",
        "description": "Start a sensitivity sweep of one parameter across several values (write).",
        "input_schema": {
            "type": "object",
            "properties": {"param": {"type": "string"}, "values": {"type": "array", "items": {"type": "number"}}},
            "required": ["param", "values"],
        },
    },
    {
        "name": "create_optimization",
        "description": "Start an optimization search with weighted objectives (write).",
        "input_schema": {
            "type": "object",
            "properties": {"objectives": {"type": "object"}, "constraints": {"type": "object"}},
            "required": ["objectives"],
        },
    },
    {
        "name": "auto_populate_habitation",
        "description": "Fill in missing roads, rainfall and terrain data for this habitation from live public data sources (write).",
        "input_schema": {"type": "object", "properties": {"parameter_set_id": {"type": "string"}}},
    },
]

# keyword -> tool name, checked in order (first match wins). Deliberately
# simple: this is the offline fallback, not a substitute for a real model.
_KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bauto.?populat|\bautofill|\bfill in\b|\bfetch (the )?(road|rainfall|terrain|elevation)", re.I), "auto_populate_habitation"),
    (re.compile(r"\bbudget\b|\bcost\b|\bopex\b|\bcapex\b|\bnpv\b", re.I), "get_budget"),
    (re.compile(r"\bfinding|\bexhaust|\bshortfall|\bshortage|\bvehicle|\bsaturat", re.I), "get_run_findings"),
    (re.compile(r"\bcompare\b|\bcomparison\b|\bversus\b|\bvs\.?\b", re.I), "compare_runs"),
    (re.compile(r"\bdiffer|\bdiverg", re.I), "explain_difference"),
    (re.compile(r"\boptimi[sz]e|\boptimization|\bbest plan\b", re.I), "create_optimization"),
    (re.compile(r"\bsensitivity\b|\bsweep\b|\belasticity\b", re.I), "run_sensitivity"),
    (re.compile(r"\bflood\b|\bcalamity\b|\bscenario\b|\bstrike\b|\bmonsoon\b", re.I), "create_scenario_run"),
    (re.compile(r"\brun\b|\bruns\b|\bsimulation", re.I), "list_runs"),
    (re.compile(r"\bsummary\b|\boverview\b|\bhabitation\b|\bprofile\b", re.I), "get_habitation_summary"),
    (re.compile(r"\byear\b|\bresult|\bcoverage\b|\blandfill\b|\bghg\b|\bemission", re.I), "get_run_result"),
]


def _extract_uuids(text: str) -> list[str]:
    return _UUID_RE.findall(text)


def deterministic_match(message: str, default_run_id: str | None) -> tuple[str | None, dict[str, Any]]:
    ids = _extract_uuids(message)
    for pattern, tool_name in _KEYWORD_RULES:
        if not pattern.search(message):
            continue
        args: dict[str, Any] = {}
        if tool_name in ("get_run_result", "get_run_findings", "get_budget"):
            run_id = ids[0] if ids else default_run_id
            if run_id is None:
                return None, {}
            args["run_id"] = run_id
        elif tool_name == "compare_runs":
            if len(ids) < 2:
                return None, {}
            args["run_ids"] = ids[:5]
        elif tool_name == "explain_difference":
            if len(ids) < 2:
                return None, {}
            args["run_a"], args["run_b"] = ids[0], ids[1]
        elif tool_name == "create_scenario_run":
            if default_run_id is None:
                return None, {}
            args["base_run_id"] = ids[0] if ids else default_run_id
            args["events"] = [{"event_type": "FLOOD", "start_month": 6, "duration_months": 2, "severity": "MODERATE"}]
        elif tool_name == "run_sensitivity":
            numbers = [float(n) for n in _FLOAT_RE.findall(message)]
            args["param"] = "demography.annual_growth_rate_pct"
            args["values"] = numbers if len(numbers) >= 2 else [0.0, 2.0, 4.0]
        elif tool_name == "create_optimization":
            args["objectives"] = {"MIN_COST": 0.5, "MIN_LANDFILL": 0.5}
            args["constraints"] = {}
        return tool_name, args
    return None, {}


def _anthropic_client():
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def llm_match(message: str, history: list[dict[str, str]], default_run_id: str | None) -> tuple[str | None, dict[str, Any]] | None:
    """Returns None (not (None, {})) on any provider failure, so the caller
    can tell "the model chose no tool" apart from "the model was
    unreachable" and fall back to the deterministic matcher for the latter."""
    if not settings.anthropic_api_key:
        return None
    try:
        client = _anthropic_client()
        system = (
            "You are the intent router for a waste-management simulation tool. "
            "Choose at most one tool that answers the user's question, using the fixed schema given. "
            "If no tool clearly answers it, call no tool at all — never guess an argument you were not given. "
            f"The current run in context, if the user says 'this run', is: {default_run_id or 'none'}."
        )
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=512,
            system=system,
            messages=[*history, {"role": "user", "content": message}],
            tools=TOOL_SCHEMA,
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.name, dict(block.input)
        return None, {}
    except Exception:
        return None


def extract_intent(message: str, history: list[dict[str, str]], default_run_id: str | None) -> tuple[str | None, dict[str, Any], bool]:
    """Returns (tool_name, arguments, used_llm)."""
    result = llm_match(message, history, default_run_id)
    if result is not None:
        return result[0], result[1], True
    tool_name, args = deterministic_match(message, default_run_id)
    return tool_name, args, False


def extract_numbers(text: str) -> set[str]:
    """Normalised numeric tokens in `text` (commas stripped, trailing zeros
    kept as-is) — used by grounding.py to verify an LLM-polished answer
    never introduces a figure that wasn't already in the grounded facts."""
    return {tok.replace(",", "") for tok in re.findall(r"-?\d[\d,]*\.?\d*", text)}


__all__ = ["extract_intent", "deterministic_match", "llm_match", "extract_numbers", "TOOL_SCHEMA"]
