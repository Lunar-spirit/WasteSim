"""Numeric grounding and citations (design 5.8 / BR-30: "every numeric value
in a chat answer is read from a stored row and substituted by the backend;
the language model contributes prose only").

The deterministic sentence built here from the tool's own result dict is
always correct by construction — every number in it came straight out of
the result the service call returned. When an LLM is configured, it is
allowed to rephrase that sentence, but only after its rewrite is checked to
contain no number that isn't already in the deterministic version; a
rewrite that fails this check is discarded and the deterministic sentence
is used instead. This is what keeps BR-30 true even though a real language
model is in the loop — the model can never be the last word on a figure.
"""

from __future__ import annotations

from typing import Any

from app.chat.router_llm import extract_numbers
from app.core.config import settings


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def build_grounded_answer(tool_name: str, run_id: str | None, arguments: dict[str, Any], result: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """Returns (deterministic_prose, citations)."""
    citations: list[dict[str, Any]] = []
    sentences: list[str] = []

    if tool_name == "get_habitation_summary":
        sentences.append(
            f"{result['name']} is a {result['habitation_type']} in status {result['status']}, "
            f"currently on parameter version {result['active_parameter_set_version']}, with "
            f"{len(result['layers'])} GIS layer(s) on file."
        )
        citations.append({"habitation_id": result["habitation_id"], "field": "status"})

    elif tool_name == "list_runs":
        sentences.append(f"There are {len(result['runs'])} run(s) for this habitation.")
        for run in result["runs"][:5]:
            sentences.append(f"- {run['label'] or run['run_id']} ({run['run_type']}, {run['status']}).")
            citations.append({"run_id": run["run_id"], "field": "status"})

    elif tool_name == "get_run_result":
        if "message" in result:
            sentences.append(result["message"])
        else:
            for year in result["years"]:
                parts = ", ".join(f"{k}={_fmt(v)}" for k, v in year.items() if k != "year_index" and v is not None)
                sentences.append(f"Year {year['year_index']}: {parts}.")
                citations.append({"run_id": result["run_id"], "year_index": year["year_index"]})

    elif tool_name == "get_run_findings":
        for finding in result["findings"]:
            value = f" = {_fmt(finding['numeric_value'])}" if finding["numeric_value"] is not None else ""
            sentences.append(f"{finding['code']}{value}: {finding['message']}")
            citations.append({"run_id": result["run_id"], "indicator": finding["code"]})

    elif tool_name == "compare_runs":
        for indicator, points in result["series"].items():
            if not points:
                continue
            last = points[-1]
            values = ", ".join(f"{rid}={_fmt(v)}" for rid, v in last["values"].items() if v is not None)
            sentences.append(f"{indicator} at year {last['year_index']}: {values}.")
            for run_id in last["values"]:
                citations.append({"run_id": run_id, "year_index": last["year_index"], "indicator": indicator})

    elif tool_name == "get_budget":
        sentences.append(
            f"Total cost is INR {_fmt(result['total_cost_inr'])} "
            f"(opex INR {_fmt(result['total_opex_inr'])}, capex INR {_fmt(result['total_capex_inr'])}), "
            f"NPV INR {_fmt(result['npv_total_cost_inr'])}."
        )
        citations.append({"run_id": result["run_id"], "indicator": "total_cost_inr"})

    elif tool_name == "explain_difference":
        for row in result["largest_divergences"]:
            sentences.append(f"{row['indicator']} diverges most in month {row['month_index']} (|difference| = {_fmt(row['abs_difference'])}).")
            citations.append({"run_id": result["run_a"], "month_index": row["month_index"], "indicator": row["indicator"]})
            citations.append({"run_id": result["run_b"], "month_index": row["month_index"], "indicator": row["indicator"]})

    elif tool_name in ("create_scenario_run", "run_sensitivity", "create_optimization"):
        job_id = result.get("job_id")
        new_id = result.get("run_id") or result.get("analysis_id") or result.get("optimization_id")
        sentences.append(f"Started — id {new_id}, job {job_id}. Poll its status endpoint for the result.")
        citations.append({"job_id": job_id})

    else:
        sentences.append("Done.")

    return " ".join(sentences) if sentences else "I found nothing to report.", citations


def polish_prose(question: str, deterministic_prose: str) -> str:
    """Best-effort LLM rewrite of `deterministic_prose`, verified to
    introduce no new number; returns the deterministic prose unchanged on
    any failure or verification miss (EXT-05 / T-57)."""
    if not settings.anthropic_api_key or not deterministic_prose:
        return deterministic_prose
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=300,
            system=(
                "Rewrite the following grounded facts into one short, natural-language answer to the user's "
                "question. You MUST NOT add, remove, or alter any number — copy every figure verbatim. "
                "Do not invent facts not present below."
            ),
            messages=[{"role": "user", "content": f"Question: {question}\n\nGrounded facts: {deterministic_prose}"}],
        )
        polished = "".join(block.text for block in response.content if block.type == "text").strip()
        if not polished:
            return deterministic_prose
        if not extract_numbers(polished) <= extract_numbers(deterministic_prose):
            return deterministic_prose  # the model added a number we can't verify — reject it
        return polished
    except Exception:
        return deterministic_prose
