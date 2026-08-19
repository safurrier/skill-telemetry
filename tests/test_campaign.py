from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

import skill_telemetry.campaign as campaign_module
from skill_telemetry.campaign import (
    CampaignError,
    CaseObservation,
    load_manifest,
    load_observations,
    score_campaign,
)


def _packaged_manifest() -> dict[str, object]:
    return json.loads(
        files("skill_telemetry").joinpath("campaigns/acceptance-v1.json").read_text()
    )


@pytest.mark.parametrize(
    "case_id", ["../escape", "/absolute", "a" * 65, "dot.name", "sk-proj-PRIVATE123"]
)
def test_campaign_rejects_unsafe_case_ids(tmp_path: Path, case_id: str) -> None:
    manifest = _packaged_manifest()
    cases = manifest["cases"]
    assert isinstance(cases, list)
    cases[0]["case_id"] = case_id
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(CampaignError, match="safe filename segment"):
        load_manifest(path)


def test_manifest_observation_name_rejects_traversal_and_absolute_paths(
    tmp_path: Path,
) -> None:
    for observation in (
        "../observations.json",
        "/observations.json",
        "nested/data.json",
    ):
        manifest = _packaged_manifest()
        manifest["observations"] = observation
        path = tmp_path / f"{len(observation)}.json"
        path.write_text(json.dumps(manifest))
        with pytest.raises(CampaignError, match="safe JSON filename"):
            load_manifest(path)


def test_campaign_inputs_do_not_follow_symlinks(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_packaged_manifest()))
    manifest_link = tmp_path / "manifest-link.json"
    manifest_link.symlink_to(manifest)
    with pytest.raises(CampaignError, match="unsafe or unreadable campaign"):
        load_manifest(manifest_link)

    loaded = load_manifest(manifest)
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {"schema_version": 1, "campaign_id": loaded.campaign_id, "cases": {}}
        )
    )
    observations_link = tmp_path / "observations-link.json"
    observations_link.symlink_to(observations)
    with pytest.raises(CampaignError, match="unsafe or unreadable observations"):
        load_observations(observations_link, loaded)


def test_campaign_reader_rejects_truncated_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_packaged_manifest()))
    original_read = campaign_module.os.read

    def truncated(fd: int, size: int) -> bytes:
        return b"" if size > 1 else original_read(fd, size)

    monkeypatch.setattr(campaign_module.os, "read", truncated)
    with pytest.raises(CampaignError, match="truncated campaign"):
        load_manifest(manifest)


def test_packaged_campaign_evaluates_through_production_seams() -> None:
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    assert score_campaign(manifest, observations)["passed"] is True


def test_campaign_negative_controls_wrong_skill_gates_and_rate_semantics() -> None:
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    positive = observations["pi-explicit"].events[0]
    negative = {
        **observations,
        "pi-negative-control": CaseObservation(
            events=(replace(positive, activation_id="sha256:" + "1" * 64),),
            unsupported_outcomes=(),
        ),
    }
    report = score_campaign(manifest, negative)
    assert report["passed"] is False
    assert report["gates"]["zero_false_positives"] is False

    wrong_skill = {
        **observations,
        "pi-explicit": CaseObservation(
            events=(replace(positive, skill_name="other-skill"),),
            unsupported_outcomes=(),
        ),
    }
    report = score_campaign(manifest, wrong_skill)
    assert report["cases"][0]["wrong_skill_observed"] == ["explicit-command"]
    assert report["gates"]["supported_explicit_recall_100"] is False

    delivery = score_campaign(manifest, observations, gate_set="delivery")
    assert set(delivery["gates"]) == {
        "required_evidence_supported",
        "zero_false_positives",
        "no_unexplained_provenance_errors",
        "unobservable_evidence_explicit",
    }
    failed_producer = campaign_module.add_producer_checks(
        delivery, {"pi-extension-tests": False}
    )
    assert failed_producer["passed"] is False
    assert failed_producer["gates"]["pi-extension-tests"] is False
    with pytest.raises(CampaignError, match="producer checks"):
        campaign_module.add_producer_checks(delivery, {"pi-extension-tests": 1})

    # The top-level rate counts cases; each per-stage rate counts events.
    assert report["metrics"]["unknown_rate"] == {
        "numerator": 1,
        "denominator": 16,
        "value": 1 / 16,
    }
    stages = report["metrics"]["stages"]
    assert stages["explicit-command"]["unknown_rate"]["denominator"] == 3


def test_unknown_evidence_stage_fails_closed_unless_explicitly_unsupported() -> None:
    campaign_dir = files("skill_telemetry").joinpath("campaigns")
    manifest = load_manifest(Path(str(campaign_dir / "acceptance-v1.json")))
    observations = load_observations(
        Path(str(campaign_dir / "acceptance-observations-v1.json")), manifest
    )
    case = manifest.cases[0]
    observation = observations[case.case_id]
    unknown_event = replace(observation.events[0], evidence_type="future-stage")
    changed = {
        **observations,
        case.case_id: CaseObservation(events=(unknown_event,), unsupported_outcomes=()),
    }
    report = score_campaign(manifest, changed)
    assert report["passed"] is False
    result = report["cases"][0]
    assert result["unrecognized_evidence_stages"] == ["future-stage"]

    accounted_case = replace(
        case, unobservable_outcomes=(campaign_module.UNSUPPORTED_EVIDENCE_STAGE,)
    )
    accounted_manifest = replace(manifest, cases=(accounted_case, *manifest.cases[1:]))
    changed[case.case_id] = CaseObservation(
        events=(observation.events[0], unknown_event),
        unsupported_outcomes=(campaign_module.UNSUPPORTED_EVIDENCE_STAGE,),
    )
    accounted = score_campaign(accounted_manifest, changed)
    assert accounted["cases"][0]["status"] == "unobservable"
