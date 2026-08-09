"""レポート対象期間の計算。AWS に依存しない純粋関数のみ。"""

from datetime import date, timedelta
from typing import NamedTuple


class ReportPeriod(NamedTuple):
    """レポート1回分の対象期間。

    target_*   : レポート対象（前月）
    previous_* : 前月比の比較対象（前々月）
    query_*    : Cost Explorer に渡す範囲。query_end は排他（この日を含まない）。
    """

    target_start: date
    target_end: date
    previous_start: date
    previous_end: date
    query_start: date
    query_end: date

    @property
    def target_label(self) -> str:
        """`2026-07` 形式のラベル。"""
        return self.target_start.strftime("%Y-%m")


def _first_day_of_previous_month(day: date) -> date:
    """指定日が属する月の前月1日を返す。"""
    first_of_this_month = day.replace(day=1)
    return (first_of_this_month - timedelta(days=1)).replace(day=1)


def build_report_period(today: date) -> ReportPeriod:
    """基準日から、前月（対象）と前々月（比較）の期間を組み立てる。

    Lambda は 00:00 UTC（= 09:00 JST 同日）に起動するため、UTC 日付と
    JST 日付は同じ月に属する。よって UTC の日付をそのまま基準にできる。
    """
    current_month_start = today.replace(day=1)
    target_start = _first_day_of_previous_month(current_month_start)
    previous_start = _first_day_of_previous_month(target_start)

    return ReportPeriod(
        target_start=target_start,
        target_end=current_month_start - timedelta(days=1),
        previous_start=previous_start,
        previous_end=target_start - timedelta(days=1),
        query_start=previous_start,
        query_end=current_month_start,
    )
