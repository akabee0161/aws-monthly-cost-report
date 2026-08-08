from datetime import date
from decimal import Decimal

import pytest

from cost_report import cost_explorer, handler

TOPIC_ARN = "arn:aws:sns:ap-northeast-1:123456789012:CostReportTopic"


class FakeContext(object):
    aws_request_id = "req-abc"
    invoked_function_arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:CostReportFunction"


class RecordingSns(object):
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def publish(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("sns is down")
        return {"MessageId": "mid"}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SNS_TOPIC_ARN", TOPIC_ARN)
    monkeypatch.setenv("TOP_N_SERVICES", "10")


def _install(monkeypatch, sns_client, fetch):
    monkeypatch.setattr(handler, "build_sns_client", lambda: sns_client)
    monkeypatch.setattr(handler, "build_ce_client", lambda: object())
    monkeypatch.setattr(handler.cost_explorer, "fetch_monthly_costs", fetch)


def _costs():
    return {
        date(2026, 7, 1): cost_explorer.MonthlyCost(
            period_start=date(2026, 7, 1),
            total=Decimal("66.05"),
            by_service={"Amazon RDS": Decimal("45.20")},
            unit="USD",
        ),
        date(2026, 6, 1): cost_explorer.MonthlyCost(
            period_start=date(2026, 6, 1),
            total=Decimal("64.20"),
            by_service={"Amazon RDS": Decimal("43.10")},
            unit="USD",
        ),
    }


def test_正常時はレポートを1通publishする(env, monkeypatch):
    sns_client = RecordingSns()
    _install(monkeypatch, sns_client, lambda client, period: _costs())
    monkeypatch.setattr(handler, "_today", lambda: date(2026, 8, 5))

    result = handler.lambda_handler({}, FakeContext())

    assert result == {"status": "ok", "period": "2026-07"}
    assert len(sns_client.calls) == 1
    assert sns_client.calls[0]["TopicArn"] == TOPIC_ARN
    assert sns_client.calls[0]["Subject"].startswith("[AWS Cost] 2026-07 total")
    assert "アカウント : 123456789012" in sns_client.calls[0]["Message"]


def test_CE失敗時はエラー通知を1通送って例外を再送出する(env, monkeypatch):
    sns_client = RecordingSns()

    def failing_fetch(client, period):
        raise RuntimeError("cost explorer exploded")

    _install(monkeypatch, sns_client, failing_fetch)
    monkeypatch.setattr(handler, "_today", lambda: date(2026, 8, 5))

    with pytest.raises(RuntimeError, match="cost explorer exploded"):
        handler.lambda_handler({}, FakeContext())

    assert len(sns_client.calls) == 1
    assert sns_client.calls[0]["Subject"] == "[AWS Cost][ERROR] monthly cost report failed"
    assert "エラー種別   : RuntimeError" in sns_client.calls[0]["Message"]
    assert "リクエストID : req-abc" in sns_client.calls[0]["Message"]


def test_エラー通知のpublishも失敗した場合は元の例外を再送出する(env, monkeypatch):
    sns_client = RecordingSns(fail=True)

    def failing_fetch(client, period):
        raise ValueError("original failure")

    _install(monkeypatch, sns_client, failing_fetch)
    monkeypatch.setattr(handler, "_today", lambda: date(2026, 8, 5))

    with pytest.raises(ValueError, match="original failure"):
        handler.lambda_handler({}, FakeContext())

    assert len(sns_client.calls) == 1


def test_SNS_TOPIC_ARN未設定ならKeyErrorを送出する(monkeypatch):
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)

    with pytest.raises(KeyError):
        handler.lambda_handler({}, FakeContext())
