import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".claude/skills/dakwah-content-discovery/scripts/validate-proposal.py"
FIXTURE = ROOT / "tests/phase3/fixtures/simulated_proposal.json"
spec = importlib.util.spec_from_file_location("proposal_validator", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def proposal():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_simulated_fixture_matches_schema_and_normalized_score():
    assert validator.validate(proposal(), json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8"))) == []


def test_rejects_invalid_timestamp_and_duration():
    p = proposal()
    p["end_time"] = 110
    p["duration"] = 5
    errors = validator.validate(p, json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8")))
    assert any("end_time must be greater" in e for e in errors)
    assert any("duration does not match" in e for e in errors)


def test_requires_verbatim_source_excerpt_field_and_valid_score():
    p = proposal()
    del p["transcript_excerpt"]
    p["overall_score"] = 100
    errors = validator.validate(p, json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8")))
    assert any("transcript_excerpt" in e for e in errors)
    assert any("normalized evaluated-weight score" in e for e in errors)


def test_rejects_guessed_technical_score_when_media_was_not_reviewed():
    p = proposal()
    p["scoring_breakdown"]["technical_quality"]["score"] = 90
    errors = validator.validate(p, json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8")))
    assert any("not_evaluated technical_quality" in e for e in errors)


def test_rejects_duplicate_same_video_spans():
    p = proposal()
    duplicate = dict(p, proposal_id="simulated-proposal-002")
    errors = validator.validate([p, duplicate], json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8")))
    assert any("overlap by at least 80%" in e for e in errors)
