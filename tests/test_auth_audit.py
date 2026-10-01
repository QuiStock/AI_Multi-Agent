from __future__ import annotations

import logging

from src.observability.audit import record_authentication_denial


def test_authentication_audit_records_reason_without_identity_or_credential(
    caplog: logging.LogRecord,
) -> None:
    with caplog.at_level(logging.WARNING, logger="security.audit"):
        record_authentication_denial("credential_invalid")

    record = caplog.records[0]
    assert record.reason_code == "credential_invalid"
    assert not hasattr(record, "email")
    assert not hasattr(record, "token")
