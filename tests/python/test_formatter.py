from datetime import date
from decimal import Decimal

from cost_report import formatter
from cost_report.cost_explorer import MonthlyCost
from cost_report.periods import build_report_period

PERIOD = build_report_period(date(2026, 8, 5))


def _cost(period_start, services):
    by_service = {name: Decimal(amount) for name, amount in services.items()}
    return MonthlyCost(
        period_start=period_start,
        total=sum(by_service.values(), Decimal(0)),
        by_service=by_service,
        unit="USD",
    )


TARGET = _cost(date(2026, 7, 1), {"Amazon RDS": "45.20", "Amazon S3": "12.55", "AWS Lambda": "8.30"})
PREVIOUS = _cost(date(2026, 6, 1), {"Amazon RDS": "43.10", "Amazon S3": "12.95", "AWS Lambda": "8.15"})


def test_件名はASCIIのみで構成される():
    subject = formatter.build_subject(PERIOD, TARGET, PREVIOUS)

    subject.encode("ascii")  # 非 ASCII が含まれると UnicodeEncodeError
    # 66.05 と 64.20 の差 1.85 → 1.85 / 64.20 * 100 = 2.88... → +2.9%
    assert subject == "[AWS Cost] 2026-07 total 66.05 USD (+2.9%)"


def test_件名は100文字未満に収まる():
    subject = formatter.build_subject(PERIOD, TARGET, PREVIOUS)

    assert len(subject) < 100


def test_前月合計が0なら件名から変化率を省く():
    empty_previous = _cost(date(2026, 6, 1), {})

    subject = formatter.build_subject(PERIOD, TARGET, empty_previous)

    assert subject == "[AWS Cost] 2026-07 total 66.05 USD"


def test_エラー件名はASCIIのみ():
    subject = formatter.build_error_subject()

    subject.encode("ascii")
    assert subject == "[AWS Cost][ERROR] monthly cost report failed"


def test_本文にアカウントIDと対象期間と合計が含まれる():
    body = formatter.build_body(PERIOD, TARGET, PREVIOUS, "123456789012")

    assert "アカウント : 123456789012" in body
    assert "対象期間   : 2026-07-01 〜 2026-07-31" in body
    assert "当月    : 66.05 USD" in body
    assert "前月    : 64.20 USD" in body
    assert "差分    : +1.85 USD (+2.9%)" in body


def test_本文のサービス別内訳は金額降順で前月比を併記する():
    body = formatter.build_body(PERIOD, TARGET, PREVIOUS, "123456789012")
    lines = [line for line in body.splitlines() if "Amazon" in line or "Lambda" in line]

    assert lines[0].strip().startswith("1. Amazon RDS")
    assert lines[0].rstrip().endswith("45.20 USD  (+2.10)")
    assert lines[1].strip().startswith("2. Amazon S3")
    assert lines[1].rstrip().endswith("12.55 USD  (-0.40)")
    assert lines[2].strip().startswith("3. AWS Lambda")
    assert lines[2].rstrip().endswith("8.30 USD  (+0.15)")


def test_上位N件を超える分はその他に集約する():
    # 金額は 20, 19, ... 9 の12件。上位10件は 20〜11、残り2件は 10 と 9。
    services = {"Service{:02d}".format(i): str(20 - i) for i in range(12)}
    target = _cost(date(2026, 7, 1), services)

    body = formatter.build_body(PERIOD, target, _cost(date(2026, 6, 1), {}), "123456789012", top_n=10)

    assert "上位10件" in body
    assert "その他 (2件)" in body
    assert "19.00 USD" in body  # 10.00 + 9.00


def test_前月合計が0なら本文の変化率を非表示にする():
    body = formatter.build_body(PERIOD, TARGET, _cost(date(2026, 6, 1), {}), "123456789012")

    assert "差分    : +66.05 USD (前月 0.00 のため率は非表示)" in body


def test_コストデータが0件でも正常な本文を返す():
    empty = _cost(date(2026, 7, 1), {})

    body = formatter.build_body(PERIOD, empty, _cost(date(2026, 6, 1), {}), "123456789012")

    assert "対象期間のコストデータがありません。" in body
    assert "当月    : 0.00 USD" in body


def test_前々月に存在しないサービスは差分に全額が出る():
    target = _cost(date(2026, 7, 1), {"Amazon Bedrock": "2.40"})

    body = formatter.build_body(PERIOD, target, _cost(date(2026, 6, 1), {}), "123456789012")

    assert "(+2.40)" in body


def test_全角を含む行も表示幅で桁が揃う():
    services = {"Service{:02d}".format(i): "1.00" for i in range(11)}
    target = _cost(date(2026, 7, 1), services)

    body = formatter.build_body(PERIOD, target, _cost(date(2026, 6, 1), {}), "123456789012", top_n=10)
    other_line = [line for line in body.splitlines() if "その他" in line][0]
    first_line = [line for line in body.splitlines() if "1. Service00" in line][0]

    assert formatter.visual_width(other_line) == formatter.visual_width(first_line.split("  (")[0])


def test_エラー本文に例外種別とリクエストIDが含まれる():
    error = ValueError("boom")

    body = formatter.build_error_body(PERIOD, error, "req-123")

    assert "エラー種別   : ValueError" in body
    assert "エラー内容   : boom" in body
    assert "リクエストID : req-123" in body
    assert "対象期間     : 2026-07-01 〜 2026-07-31" in body
