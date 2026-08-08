import { App } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import { AwsMonthlyCostReportStack } from "../lib/aws-monthly-cost-report-stack";

function buildTemplate(props: { topNServices?: number; scheduleDayOfMonth?: string } = {}): Template {
  const app = new App();
  const stack = new AwsMonthlyCostReportStack(app, "TestStack", {
    notifyEmail: "test@example.com",
    env: { account: "123456789012", region: "ap-northeast-1" },
    ...props,
  });
  return Template.fromStack(stack);
}

test("SNS トピックと Email サブスクリプションを作成する", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::SNS::Topic", {
    DisplayName: "AWS Monthly Cost Report",
  });
  template.hasResourceProperties("AWS::SNS::Subscription", {
    Protocol: "email",
    Endpoint: "test@example.com",
  });
});

test("Lambda は Python 3.13 で retryAttempts が 0 である", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::Lambda::Function", {
    Runtime: "python3.13",
    Handler: "cost_report.handler.lambda_handler",
    Timeout: 60,
    MemorySize: 256,
  });
  template.hasResourceProperties("AWS::Lambda::EventInvokeConfig", {
    MaximumRetryAttempts: 0,
  });
});

test("EventBridge は毎月5日 00:00 UTC に起動する", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::Events::Rule", {
    ScheduleExpression: "cron(0 0 5 * ? *)",
    State: "ENABLED",
  });
});

test("実行日は上書きできる", () => {
  const template = buildTemplate({ scheduleDayOfMonth: "3" });

  template.hasResourceProperties("AWS::Events::Rule", {
    ScheduleExpression: "cron(0 0 3 * ? *)",
  });
});

test("実行ロールに ce:GetCostAndUsage が付与される", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: Match.objectLike({
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: "ce:GetCostAndUsage",
          Effect: "Allow",
          Resource: "*",
        }),
      ]),
    }),
  });
});

test("sns:Publish は作成したトピックに限定される", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::IAM::Policy", {
    PolicyDocument: Match.objectLike({
      Statement: Match.arrayWith([
        Match.objectLike({
          Action: "sns:Publish",
          Effect: "Allow",
          Resource: { Ref: Match.stringLikeRegexp("CostReportTopic") },
        }),
      ]),
    }),
  });
});

test("実行ロールに広範なワイルドカード権限が含まれない", () => {
  const template = buildTemplate();
  const policies = template.findResources("AWS::IAM::Policy");
  const actions = Object.values(policies).flatMap((policy: any) =>
    policy.Properties.PolicyDocument.Statement.flatMap((statement: any) =>
      Array.isArray(statement.Action) ? statement.Action : [statement.Action],
    ),
  );

  expect(actions).not.toContain("*");
  expect(actions).not.toContain("ce:*");
  expect(actions).not.toContain("logs:*");
  expect(actions).not.toContain("sns:*");
});

test("ロググループの保持期間は1ヶ月である", () => {
  const template = buildTemplate();

  template.hasResourceProperties("AWS::Logs::LogGroup", {
    RetentionInDays: 30,
  });
});

test("環境変数 TOP_N_SERVICES は既定で 10、上書き可能である", () => {
  buildTemplate().hasResourceProperties("AWS::Lambda::Function", {
    Environment: { Variables: Match.objectLike({ TOP_N_SERVICES: "10" }) },
  });

  buildTemplate({ topNServices: 5 }).hasResourceProperties("AWS::Lambda::Function", {
    Environment: { Variables: Match.objectLike({ TOP_N_SERVICES: "5" }) },
  });
});
