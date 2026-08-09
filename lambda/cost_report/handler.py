"""Lambda エントリポイント。取得・整形・通知のオーケストレーションとエラーハンドリング。"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Dict

import boto3
from botocore.config import Config

from . import cost_explorer, formatter, notifier, periods

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

# Cost Explorer のエンドポイントは us-east-1 固定。デプロイ先リージョンに関わらず明示する。
CE_REGION = "us-east-1"

# 非同期呼び出しの再試行は Lambda 側で 0 にしてあるため、
# 一時障害の吸収はこのクライアント内リトライで完結させる。
_BOTO_CONFIG = Config(retries={"mode": "standard", "max_attempts": 5})


def build_ce_client():
    return boto3.client("ce", region_name=CE_REGION, config=_BOTO_CONFIG)


def build_sns_client():
    return boto3.client("sns", config=_BOTO_CONFIG)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _account_id(context) -> str:
    """Lambda の ARN からアカウント ID を取り出す。"""
    arn = getattr(context, "invoked_function_arn", "")
    parts = arn.split(":")
    return parts[4] if len(parts) > 4 else "unknown"


def lambda_handler(event, context) -> Dict[str, str]:
    # 通知先が無ければエラー通知も送れないため、ここで失敗させて CloudWatch に残す。
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    period = periods.build_report_period(_today())
    sns_client = build_sns_client()

    try:
        # topic_arn と違い通知先は判明しているので、解析失敗も try 内でエラー通知に乗せる。
        top_n = int(os.environ.get("TOP_N_SERVICES", str(formatter.DEFAULT_TOP_N)))

        costs = cost_explorer.fetch_monthly_costs(build_ce_client(), period)
        target = cost_explorer.get_month(costs, period.target_start)
        previous = cost_explorer.get_month(costs, period.previous_start)

        notifier.publish(
            sns_client,
            topic_arn,
            formatter.build_subject(period, target, previous),
            formatter.build_body(period, target, previous, _account_id(context), top_n),
        )
        LOGGER.info("月次コストレポートを送信しました: %s", period.target_label)
        return {"status": "ok", "period": period.target_label}

    except Exception as error:
        LOGGER.exception("月次コストレポートの生成に失敗しました")
        request_id = getattr(context, "aws_request_id", "unknown")
        try:
            notifier.publish(
                sns_client,
                topic_arn,
                formatter.build_error_subject(),
                formatter.build_error_body(period, error, request_id),
            )
        except Exception:
            # エラー通知の失敗で元の原因を隠さない。ログに残して元の例外を再送出する。
            LOGGER.exception("エラー通知の送信にも失敗しました")
        raise
