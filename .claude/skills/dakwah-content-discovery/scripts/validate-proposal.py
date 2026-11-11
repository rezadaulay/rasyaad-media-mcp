#!/usr/bin/env python3
"""Validate one proposal or a list of proposals against the skill contract."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "content-proposal.schema.json"
WEIGHTS = {
    "message_benefit": 25,
    "context_independence": 25,
    "opening_hook": 20,
    "clarity": 15,
    "audience_relevance": 10,
    "technical_quality": 5,
}


def validate(data, schema):
    errors = []
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        return ["Install the project requirements (jsonschema) to validate against JSON Schema."]
    proposals = data if isinstance(data, list) else [data]
    schema_validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for i, proposal in enumerate(proposals):
        errors.extend(f"proposal[{i}] schema: {e.message} at {list(e.absolute_path)}" for e in schema_validator.iter_errors(proposal))
    seen = set()
    for i, p in enumerate(proposals):
        prefix = f"proposal[{i}]"
        if not isinstance(p, dict):
            continue
        pid = p.get("proposal_id")
        if pid in seen:
            errors.append(f"{prefix}: duplicate proposal_id {pid!r}")
        seen.add(pid)
        start, end, duration = p.get("start_time"), p.get("end_time"), p.get("duration")
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (start, end, duration)):
            if end <= start:
                errors.append(f"{prefix}: end_time must be greater than start_time")
            if abs((end - start) - duration) > 1.01:
                errors.append(f"{prefix}: duration does not match end_time - start_time within timestamp rounding tolerance")
        breakdown = p.get("scoring_breakdown")
        coverage = p.get("evaluation_coverage")
        if isinstance(breakdown, dict) and isinstance(coverage, dict):
            evaluated = []
            for name, weight in WEIGHTS.items():
                dim = breakdown.get(name, {})
                if not isinstance(dim, dict):
                    continue
                if dim.get("weight") != weight:
                    errors.append(f"{prefix}: {name} weight must equal {weight}")
                status, score = dim.get("status"), dim.get("score")
                if status == "evaluated":
                    if not isinstance(score, (int, float)) or isinstance(score, bool):
                        errors.append(f"{prefix}: evaluated {name} needs a numeric score")
                    else:
                        evaluated.append((weight, score, name))
                elif status == "not_evaluated" and score is not None:
                    errors.append(f"{prefix}: not_evaluated {name} must have null score")
            total_weight = sum(w for w, _, _ in evaluated)
            expected_coverage = total_weight / 100
            actual_coverage = coverage.get("evaluated_weight")
            if isinstance(actual_coverage, (int, float)) and abs(actual_coverage - expected_coverage) > .005:
                errors.append(f"{prefix}: evaluated_weight should be {expected_coverage:.2f}")
            expected_names = {name for _, _, name in evaluated}
            if set(coverage.get("evaluated_dimensions", [])) != expected_names:
                errors.append(f"{prefix}: evaluated_dimensions do not match scoring dimension statuses")
            overall = p.get("overall_score")
            technical = breakdown.get("technical_quality", {})
            if technical.get("status") == "not_evaluated" and technical.get("score") is not None:
                errors.append(f"{prefix}: technical quality cannot be guessed when not evaluated")
            if evaluated:
                expected_score = sum(w * s for w, s, _ in evaluated) / total_weight
                if not isinstance(overall, (int, float)) or abs(overall - expected_score) > 1.01:
                    errors.append(f"{prefix}: overall_score should be normalized evaluated-weight score {expected_score:.2f}")
            elif overall is not None:
                errors.append(f"{prefix}: overall_score must be null when no dimensions were evaluated")
    for i, left in enumerate(proposals):
        if not isinstance(left, dict):
            continue
        for j in range(i + 1, len(proposals)):
            right = proposals[j]
            if not isinstance(right, dict) or left.get("video_id") != right.get("video_id"):
                continue
            a, b = left.get("start_time"), left.get("end_time")
            c, d = right.get("start_time"), right.get("end_time")
            if not all(isinstance(x, (int, float)) for x in (a, b, c, d)):
                continue
            overlap = max(0, min(b, d) - max(a, c))
            shorter = min(b - a, d - c)
            if shorter > 0 and overlap / shorter >= .8:
                errors.append(f"proposal[{i}] and proposal[{j}]: same-video spans overlap by at least 80%; review for duplication")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_file", type=Path)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args()
    try:
        data = json.loads(args.proposal_file.read_text(encoding="utf-8"))
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    errors = validate(data, schema)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    count = len(data) if isinstance(data, list) else 1
    print(f"Valid: {count} proposal(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
