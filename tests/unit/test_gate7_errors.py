"""Gate 7 Wave-0 errors remain typed, serialisable and registered."""

from __future__ import annotations

import inspect

from sol_claude_dispatcher import errors


WAVE0_ERROR_NAMES = {
    "AdminAllowlistPresent",
    "AmbiguousRepositoryHistory",
    "AttributionClosureViolated",
    "BaseBlobUnreadable",
    "BaseCommitAbsent",
    "BaseObjectVerificationFailed",
    "BaseRefNotACommitObject",
    "BaseTreeSnapshotFailed",
    "CheckoutTransformationBudgetExceeded",
    "DispatcherSetupTouchedPrimaryTree",
    "EvidenceFreezeViolated",
    "FilesystemSnapshotFailed",
    "ForbiddenGitInvocation",
    "GitAdministrativeCaptureFailed",
    "GitArgvPinDisplaced",
    "GitBeforeEstablishment",
    "GitIdentityDerivationAttempted",
    "HistoryIdentityDerivationDisagreement",
    "InventoryFilesystemUnsupported",
    "PathIdentityUnrepresentable",
    "PhaseRegression",
    "ProductionBaseRefNotExact",
    "RefResolutionFailed",
    "RepositoryAdministrationUnestablished",
    "RepositoryAdministrationUnreconciled",
    "RepositoryAdministrationUnsupported",
    "RepositoryAuthorityCaptureFailed",
    "RepositoryIdentityUnsealed",
    "RepositoryLayoutUnreadable",
    "RepositoryObjectStoreEntryUnsupported",
    "RepositoryObjectStoreMalformed",
    "RepositoryRootDrift",
    "RunFinalizationFailed",
    "SealAbsentAfterWorker",
    "SealBudgetExceeded",
    "SealIntegrityFailed",
    "SealPinSetStale",
    "SealProvenanceInvalid",
    "SnapshotBudgetExceeded",
    "StoreRoutingUnreadable",
    "UnsupportedObjectFormat",
    "UnsupportedRefStorage",
    "ValidationAttributionUnknown",
    "ValidationTouchedAdministrativeState",
    "ValidationTouchedPrimaryTree",
    "WorkerAttributionAmbiguous",
    "WorkerExitSnapshotMissing",
    "WorktreeGitdirNotDispatcherOwned",
    "WorktreeGitfileMalformed",
    "WorktreeGitfileNotRegular",
    "WorktreeHeadNotRegular",
    "WorktreeIndirectionChanged",
    "WorktreeSealSchemaUnsupported",
}


def test_complete_wave0_error_taxonomy_is_exported_and_registered() -> None:
    assert WAVE0_ERROR_NAMES <= set(errors.__all__)
    assert WAVE0_ERROR_NAMES <= set(errors.ERROR_CODES)


def test_every_wave0_error_has_a_stable_unique_code_and_payload() -> None:
    codes: set[str] = set()
    for name in sorted(WAVE0_ERROR_NAMES):
        error_type = getattr(errors, name)
        assert inspect.isclass(error_type)
        assert issubclass(error_type, errors.DispatcherError)
        assert error_type.code == name
        instance = error_type("one sentence", details={"marker": name})
        assert instance.to_payload() == {
            "error": name,
            "message": "one sentence",
            "retryable": False,
            "details": {"marker": name},
        }
        assert name not in codes
        codes.add(name)


def test_internal_invariant_errors_are_internal_dispatcher_errors() -> None:
    internal = {
        "AdminAllowlistPresent",
        "AttributionClosureViolated",
        "ForbiddenGitInvocation",
        "GitArgvPinDisplaced",
        "GitBeforeEstablishment",
        "GitIdentityDerivationAttempted",
        "PhaseRegression",
        "SealProvenanceInvalid",
    }
    for name in internal:
        assert issubclass(getattr(errors, name), errors.InternalDispatcherError)


def test_repository_admin_divergence_is_not_retryable() -> None:
    assert errors.RepositoryAdministrationUnreconciled.retryable is False
    assert errors.RepositoryObjectStoreMalformed.retryable is False
    assert errors.RepositoryObjectStoreEntryUnsupported.retryable is False

