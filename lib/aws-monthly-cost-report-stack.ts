import * as path from "path";
import { Duration, RemovalPolicy, Stack, StackProps } from "aws-cdk-lib";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions";
import { Construct } from "constructs";

export interface AwsMonthlyCostReportStackProps extends StackProps {
  /** 通知先メールアドレス。デプロイ後に確認メールの承認が必要。 */
  readonly notifyEmail: string;
  /** サービス別内訳に列挙する件数。既定 10。 */
  readonly topNServices?: number;
  /** 実行日（毎月の日付）。既定 "5"。 */
  readonly scheduleDayOfMonth?: string;
}

const DEFAULT_TOP_N_SERVICES = 10;
const DEFAULT_SCHEDULE_DAY = "5";

export class AwsMonthlyCostReportStack extends Stack {
  public readonly topic: sns.Topic;
  public readonly reportFunction: lambda.Function;

  constructor(scope: Construct, id: string, props: AwsMonthlyCostReportStackProps) {
    super(scope, id, props);

    this.topic = new sns.Topic(this, "CostReportTopic", {
      displayName: "AWS Monthly Cost Report",
    });
    this.topic.addSubscription(new subscriptions.EmailSubscription(props.notifyEmail));

    const logGroup = new logs.LogGroup(this, "CostReportFunctionLogGroup", {
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    this.reportFunction = new lambda.Function(this, "CostReportFunction", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "cost_report.handler.lambda_handler",
      // ローカルの pytest が生成する .pyc を同梱しない。含めるとローカルでテストを
      // 実行したかどうかでアセットハッシュが変わり、cdk diff に偽の差分が出る。
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambda"), {
        exclude: ["**/__pycache__", "**/*.pyc"],
      }),
      timeout: Duration.seconds(60),
      memorySize: 256,
      // エラー通知が重複して届かないよう、非同期呼び出しの再試行を無効化する。
      // 一時障害は Lambda 内の boto3 リトライで吸収する。
      retryAttempts: 0,
      logGroup,
      environment: {
        SNS_TOPIC_ARN: this.topic.topicArn,
        TOP_N_SERVICES: String(props.topNServices ?? DEFAULT_TOP_N_SERVICES),
      },
    });

    // Cost Explorer はリソースレベルの権限指定をサポートしないため "*" が最小権限。
    this.reportFunction.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ce:GetCostAndUsage"],
        resources: ["*"],
      }),
    );

    this.topic.grantPublish(this.reportFunction);

    // cron は UTC 基準。0:00 UTC = 09:00 JST 同日。
    new events.Rule(this, "MonthlyScheduleRule", {
      description: "毎月の AWS コストレポートを生成する",
      schedule: events.Schedule.cron({
        minute: "0",
        hour: "0",
        day: props.scheduleDayOfMonth ?? DEFAULT_SCHEDULE_DAY,
        month: "*",
      }),
      targets: [new targets.LambdaFunction(this.reportFunction)],
    });
  }
}
