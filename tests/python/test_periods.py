from datetime import date

from cost_report.periods import build_report_period


def test_通常月_前月と前々月を返す():
    period = build_report_period(date(2026, 8, 5))

    assert period.target_start == date(2026, 7, 1)
    assert period.target_end == date(2026, 7, 31)
    assert period.previous_start == date(2026, 6, 1)
    assert period.previous_end == date(2026, 6, 30)


def test_通常月_CEクエリ範囲は前々月1日から当月1日まで():
    period = build_report_period(date(2026, 8, 5))

    assert period.query_start == date(2026, 6, 1)
    assert period.query_end == date(2026, 8, 1)


def test_1月実行時は年をまたいで前年12月と11月を返す():
    period = build_report_period(date(2026, 1, 5))

    assert period.target_start == date(2025, 12, 1)
    assert period.target_end == date(2025, 12, 31)
    assert period.previous_start == date(2025, 11, 1)
    assert period.previous_end == date(2025, 11, 30)
    assert period.query_start == date(2025, 11, 1)
    assert period.query_end == date(2026, 1, 1)


def test_うるう年の2月を対象月として正しく扱う():
    period = build_report_period(date(2024, 3, 5))

    assert period.target_start == date(2024, 2, 1)
    assert period.target_end == date(2024, 2, 29)
    assert period.previous_start == date(2024, 1, 1)
    assert period.previous_end == date(2024, 1, 31)


def test_月初1日に実行しても前月が対象になる():
    period = build_report_period(date(2026, 8, 1))

    assert period.target_start == date(2026, 7, 1)
    assert period.target_end == date(2026, 7, 31)


def test_target_labelはYYYY_MM形式を返す():
    period = build_report_period(date(2026, 8, 5))

    assert period.target_label == "2026-07"
