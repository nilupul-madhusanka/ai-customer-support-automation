from unittest.mock import MagicMock

import pytest

from models.ticket import FIELDS
from services.errors import SourceValidationError
from services.sheets_service import SheetsRepository


def sheet_with_time(repository, value, zone="Asia/Colombo"):
    service = MagicMock()
    service.spreadsheets.return_value.get.return_value.execute.return_value = {"properties": {"timeZone": zone}}
    row = {**repository.load()[0], "received_at": value}
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": [FIELDS, [row[field] for field in FIELDS]],
    }
    return SheetsRepository(service, "test-sheet"), service


def test_legacy_received_time_uses_sheet_timezone_without_writing(repository):
    sheet, service = sheet_with_time(repository, "2026-10-13T09:00:00")
    assert sheet.load()[0]["received_at"] == "2026-10-13T09:00:00+05:30"
    assert sheet.load()[0]["received_at"] == "2026-10-13T09:00:00+05:30"
    service.spreadsheets.return_value.get.assert_called_once_with(
        spreadsheetId="test-sheet", fields="properties.timeZone",
    )
    service.spreadsheets.return_value.values.return_value.update.assert_not_called()


@pytest.mark.parametrize("value", ["2026-10-13", "2026-10-13T09:00:00Z", "2026-10-13T09:00:00+02:00"])
def test_explicit_offsets_and_date_only_values_are_preserved(repository, value):
    sheet, service = sheet_with_time(repository, value)
    assert sheet.load()[0]["received_at"] == value
    service.spreadsheets.return_value.get.assert_not_called()


@pytest.mark.parametrize("zone", ["UTC", "America/New_York"])
def test_uses_actual_sheet_timezone_instead_of_assuming_colombo(repository, zone):
    sheet, _ = sheet_with_time(repository, "2026-10-13T09:00:00", zone)
    expected = "+00:00" if zone == "UTC" else "-04:00"
    assert sheet.load()[0]["received_at"].endswith(expected)


@pytest.mark.parametrize("value", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_dst_gap_and_ambiguity_require_explicit_offset(repository, value):
    sheet, _ = sheet_with_time(repository, value, "America/New_York")
    with pytest.raises(SourceValidationError, match="explicit timezone offset"):
        sheet.load()


def test_invalid_sheet_timezone_is_actionable(repository):
    sheet, _ = sheet_with_time(repository, "2026-10-13T09:00:00", "invalid-zone")
    with pytest.raises(SourceValidationError, match="spreadsheet timezone"):
        sheet.load()


def test_bad_received_time_has_relevant_guidance_without_source_value(repository):
    sheet, _ = sheet_with_time(repository, "SECRET_BAD_DATE")
    with pytest.raises(SourceValidationError) as caught:
        sheet.load()
    assert "Sheet row 2" in str(caught.value)
    assert "ISO received time" in str(caught.value)
    assert "SECRET_BAD_DATE" not in str(caught.value)
    assert "final repl" not in str(caught.value)
