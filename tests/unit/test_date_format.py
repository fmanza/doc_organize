"""Tests de `doc_organize.utils.date_format` (formato de fecha/hora parametrizable,
por defecto español/España)."""

from datetime import UTC, datetime

from doc_organize.utils.date_format import format_datetime, format_duration

_ENV_VAR_DATE_FORMAT = "DOC_ORGANIZE_DATE_FORMAT"
_ENV_VAR_TIMEZONE = "DOC_ORGANIZE_TIMEZONE"


def test_format_datetime_default_is_spanish_format_and_madrid_timezone_winter() -> None:
    # Enero: Europe/Madrid está en horario de invierno (UTC+1, sin DST).
    assert format_datetime("2026-01-15T10:00:00+00:00") == "15/01/2026 11:00:00"


def test_format_datetime_default_handles_summer_time() -> None:
    # Agosto: Europe/Madrid está en horario de verano (UTC+2, con DST).
    assert format_datetime("2026-08-01T10:00:00+00:00") == "01/08/2026 12:00:00"


def test_format_datetime_empty_or_none_returns_empty_string() -> None:
    assert format_datetime(None) == ""
    assert format_datetime("") == ""


def test_format_datetime_non_iso_value_degrades_to_raw_value_instead_of_raising() -> None:
    # Dato corrupto (backup restaurado, edición manual del JSONL, etc.): no debe
    # propagar la excepción y tumbar la página que lo renderiza -- mismo criterio
    # de tolerancia que `load_error_history` para líneas JSONL corruptas.
    assert format_datetime("no-es-una-fecha") == "no-es-una-fecha"


def test_format_datetime_invalid_timezone_degrades_to_raw_value_instead_of_raising() -> None:
    assert format_datetime("2026-01-15T10:00:00+00:00", tz_name="Zona/Inexistente") == "2026-01-15T10:00:00+00:00"


def test_format_datetime_accepts_datetime_object() -> None:
    dt = datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)
    assert format_datetime(dt) == "15/01/2026 11:00:00"


def test_format_datetime_explicit_pattern_and_tz_override_defaults() -> None:
    assert format_datetime("2026-01-15T10:00:00+00:00", pattern="%Y-%m-%d", tz_name="UTC") == "2026-01-15"


def test_format_datetime_respects_env_var_overrides(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_VAR_DATE_FORMAT, "%Y-%m-%d %H:%M")
    monkeypatch.setenv(_ENV_VAR_TIMEZONE, "UTC")
    assert format_datetime("2026-01-15T10:00:00+00:00") == "2026-01-15 10:00"


def test_format_datetime_explicit_args_take_precedence_over_env(monkeypatch) -> None:
    monkeypatch.setenv(_ENV_VAR_DATE_FORMAT, "%Y-%m-%d %H:%M")
    monkeypatch.setenv(_ENV_VAR_TIMEZONE, "UTC")
    assert format_datetime("2026-01-15T10:00:00+00:00", pattern="%d/%m/%Y", tz_name="Europe/Madrid") == "15/01/2026"


def test_format_duration_below_a_minute() -> None:
    assert format_duration(0) == "0s"
    assert format_duration(45) == "45s"


def test_format_duration_rounds_to_nearest_second() -> None:
    assert format_duration(45.6) == "46s"


def test_format_duration_minutes_and_seconds() -> None:
    assert format_duration(125.4) == "2m 5s"
    assert format_duration(60) == "1m 0s"


def test_format_duration_negative_treated_as_zero() -> None:
    """AUDIT_CODE (sesión 2026-09-04): `duration_seconds` se calcula con reloj de
    pared, no monótono -- un ajuste del reloj hacia atrás a mitad de una
    operación larga podría producir un valor negativo. Mostrarlo tal cual
    ("-1m 55s") no tiene sentido para el usuario."""
    assert format_duration(-5.0) == "0s"
    assert format_duration(-125.4) == "0s"
