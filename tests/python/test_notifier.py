import boto3
from botocore.stub import Stubber

from cost_report import notifier

TOPIC_ARN = "arn:aws:sns:ap-northeast-1:123456789012:CostReportTopic"


def test_件名と本文をトピックへpublishする():
    client = boto3.client("sns", region_name="ap-northeast-1")

    with Stubber(client) as stubber:
        stubber.add_response(
            "publish",
            {"MessageId": "mid-1"},
            {"TopicArn": TOPIC_ARN, "Subject": "[AWS Cost] 2026-07 total 66.05 USD", "Message": "本文"},
        )
        notifier.publish(client, TOPIC_ARN, "[AWS Cost] 2026-07 total 66.05 USD", "本文")

        stubber.assert_no_pending_responses()


def test_非ASCII文字は疑問符に置換される():
    assert notifier.sanitize_subject("[AWS Cost] 月次") == "[AWS Cost] ??"


def test_改行と制御文字は空白に置換される():
    assert notifier.sanitize_subject("line1\nline2\tend") == "line1 line2 end"


def test_99文字を超える件名は切り詰められる():
    result = notifier.sanitize_subject("A" * 200)

    assert len(result) == 99
    assert result.endswith("...")


def test_publish時にも件名がサニタイズされる():
    client = boto3.client("sns", region_name="ap-northeast-1")

    with Stubber(client) as stubber:
        stubber.add_response(
            "publish",
            {"MessageId": "mid-2"},
            {"TopicArn": TOPIC_ARN, "Subject": "cost ??", "Message": "本文"},
        )
        notifier.publish(client, TOPIC_ARN, "cost 月次", "本文")

        stubber.assert_no_pending_responses()
