"""Cost Explorer API の呼び出しとレスポンスの正規化。"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, NamedTuple

from .periods import ReportPeriod

METRIC = "UnblendedCost"
DEFAULT_UNIT = "USD"
_GROUP_BY_SERVICE = [{"Type": "DIMENSION", "Key": "SERVICE"}]


class MonthlyCost(NamedTuple):
    """1ヶ月分のコスト。金額はすべて Decimal で保持する。"""

    period_start: date
    total: Decimal
    by_service: Dict[str, Decimal]
    unit: str


def fetch_monthly_costs(client, period: ReportPeriod) -> Dict[date, MonthlyCost]:
    """対象期間（前々月1日〜当月1日）のコストを1リクエストで取得し、月ごとに集約する。

    query_end は排他なので、この範囲で前々月と前月の2件が返る。
    NextPageToken がある場合は全ページを取得する。
    """
    results = []  # type: List[Dict[str, Any]]
    next_token = None

    while True:
        kwargs = {
            "TimePeriod": {
                "Start": period.query_start.isoformat(),
                "End": period.query_end.isoformat(),
            },
            "Granularity": "MONTHLY",
            "Metrics": [METRIC],
            "GroupBy": _GROUP_BY_SERVICE,
        }
        if next_token is not None:
            kwargs["NextPageToken"] = next_token

        response = client.get_cost_and_usage(**kwargs)
        results.extend(response.get("ResultsByTime", []))

        next_token = response.get("NextPageToken")
        if not next_token:
            break

    return _aggregate(results)


def _aggregate(results_by_time):
    """ResultsByTime を月ごとに集約する。ページ分割時は同じ月が複数回現れるため加算する。"""
    by_month = {}  # type: Dict[date, Dict[str, Any]]

    for result in results_by_time:
        period_start = date.fromisoformat(result["TimePeriod"]["Start"])
        entry = by_month.setdefault(period_start, {"services": {}, "unit": None})

        for group in result.get("Groups", []):
            metric = group["Metrics"][METRIC]
            amount = Decimal(metric["Amount"])
            if amount == 0:
                continue
            service = group["Keys"][0]
            entry["services"][service] = entry["services"].get(service, Decimal(0)) + amount
            if entry["unit"] is None:
                entry["unit"] = metric.get("Unit")

    return {
        period_start: MonthlyCost(
            period_start=period_start,
            total=sum(entry["services"].values(), Decimal(0)),
            by_service=entry["services"],
            unit=entry["unit"] or DEFAULT_UNIT,
        )
        for period_start, entry in by_month.items()
    }


def get_month(costs: Dict[date, MonthlyCost], period_start: date) -> MonthlyCost:
    """指定月のコストを取り出す。データがない月は合計0として扱う。"""
    return costs.get(
        period_start,
        MonthlyCost(period_start=period_start, total=Decimal(0), by_service={}, unit=DEFAULT_UNIT),
    )
