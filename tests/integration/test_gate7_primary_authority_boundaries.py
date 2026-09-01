"""The dispatcher must recapture repository authority at both final boundaries."""

from __future__ import annotations


async def test_finalization_recaptures_worker_and_validation_authority(
    dispatcher, request_payload, fake_env, monkeypatch
) -> None:
    import sol_claude_dispatcher.server as server_module

    observed: list[str] = []
    original = server_module.capture_matching_repository_authority

    def recording_capture(repository_root, sealed, *, phase):
        observed.append(phase)
        return original(repository_root, sealed, phase=phase)

    monkeypatch.setattr(
        server_module, "capture_matching_repository_authority", recording_capture
    )
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "scope-violation")
    monkeypatch.setenv("FAKE_CLAUDE_TOUCH", "src/deploy/deploy.py")

    await dispatcher.dispatch_claude_task(request_payload)

    assert observed == ["worker_exit", "validation_exit"]
