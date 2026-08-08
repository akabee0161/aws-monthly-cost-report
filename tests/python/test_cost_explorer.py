from datetime import date
from decimal import Decimal

from botocore.stub import Stubber
import boto3

from cost_report import cost_explorer
from cost_report.periods import build_report_period


def _group(service, amount, unit="USD"):
    return {
        "Keys": [service],
        "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": unit}},
    }


def _result(start, end, groups, next_token=None):
    payload = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": start, "End": end},
                "Total": {},
                "Groups": groups,
                "Estimated": False,
            }
        ]
    }
    if next_token is not None:
        payload["NextPageToken"] = next_token
    return payload


def _expected_params(period, next_token=None):
    params = {
        "TimePeriod": {
            "Start": period.query_start.isoformat(),
            "End": period.query_end.isoformat(),
        },
        "Granularity": "MONTHLY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if next_token is not None:
        params["NextPageToken"] = next_token
    return params


def test_2ヶ月分を1リクエストで取得して月ごとに集約する():
    client = boto3.client("ce", region_name="us-east-1")
    period = build_report_period(date(2026, 8, 5))
    response = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-06-01", "End": "2026-07-01"},
                "Total": {},
                "Groups": [_group("Amazon RDS", "43.10"), _group("Amazon S3", "12.95")],
                "Estimated": False,
            },
            {
                "TimePeriod": {"Start": "2026-07-01", "End": "2026-08-01"},
                "Total": {},
                "Groups": [_group("Amazon RDS", "45.20"), _group("Amazon S3", "12.55")],
                "Estimated": False,
            },
        ]
    }

    with Stubber(client) as stubber:
        stubber.add_response("get_cost_and_usage", response, _expected_params(period))
        costs = cost_explorer.fetch_monthly_costs(client, period)

    assert set(costs.keys()) == {date(2026, 6, 1), date(2026, 7, 1)}
    july = costs[date(2026, 7, 1)]
    assert july.total == Decimal("57.75")
    assert july.by_service == {"Amazon RDS": Decimal("45.20"), "Amazon S3": Decimal("12.55")}
    assert july.unit == "USD"


def test_ページングされたレスポンスを全件取得して加算する():
    client = boto3.client("ce", region_name="us-east-1")
    period = build_report_period(date(2026, 8, 5))

    with Stubber(client) as stubber:
        stubber.add_response(
            "get_cost_and_usage",
            _result("2026-07-01", "2026-08-01", [_group("Amazon RDS", "45.20")], next_token="TOKEN1"),
            _expected_params(period),
        )
        stubber.add_response(
            "get_cost_and_usage",
            _result("2026-07-01", "2026-08-01", [_group("AWS Lambda", "8.30")]),
            _expected_params(period, next_token="TOKEN1"),
        )
        costs = cost_explorer.fetch_monthly_costs(client, period)

    july = costs[date(2026, 7, 1)]
    assert july.by_service == {"Amazon RDS": Decimal("45.20"), "AWS Lambda": Decimal("8.30")}
    assert july.total == Decimal("53.50")


def test_金額0のサービスは内訳から除外する():
    client = boto3.client("ce", region_name="us-east-1")
    period = build_report_period(date(2026, 8, 5))

    with Stubber(client) as stubber:
        stubber.add_response(
            "get_cost_and_usage",
            _result(
                "2026-07-01",
                "2026-08-01",
                [_group("Amazon RDS", "45.20"), _group("Amazon SNS", "0"), _group("AWS KMS", "0.0000000")],
            ),
            _expected_params(period),
        )
        costs = cost_explorer.fetch_monthly_costs(client, period)

    assert costs[date(2026, 7, 1)].by_service == {"Amazon RDS": Decimal("45.20")}


def test_通貨単位はレスポンスから採用する():
    client = boto3.client("ce", region_name="us-east-1")
    period = build_report_period(date(2026, 8, 5))

    with Stubber(client) as stubber:
        stubber.add_response(
            "get_cost_and_usage",
            _result("2026-07-01", "2026-08-01", [_group("Amazon RDS", "45.20", unit="JPY")]),
            _expected_params(period),
        )
        costs = cost_explorer.fetch_monthly_costs(client, period)

    assert costs[date(2026, 7, 1)].unit == "JPY"


def test_get_monthは該当月がなければ合計0を返す():
    result = cost_explorer.get_month({}, date(2026, 7, 1))

    assert result.period_start == date(2026, 7, 1)
    assert result.total == Decimal("0")
    assert result.by_service == {}
    assert result.unit == "USD"
