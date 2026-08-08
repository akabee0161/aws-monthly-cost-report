#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { AwsMonthlyCostReportStack } from "../lib/aws-monthly-cost-report-stack";

const app = new cdk.App();

const notifyEmail = app.node.tryGetContext("notifyEmail");
if (typeof notifyEmail !== "string" || notifyEmail.length === 0) {
  throw new Error(
    "context 'notifyEmail' が指定されていません。" +
      "`npx cdk deploy -c notifyEmail=you@example.com` の形式で指定してください。",
  );
}

const topNContext = app.node.tryGetContext("topNServices");
const scheduleDayContext = app.node.tryGetContext("scheduleDayOfMonth");

new AwsMonthlyCostReportStack(app, "AwsMonthlyCostReportStack", {
  notifyEmail,
  topNServices: topNContext === undefined ? undefined : Number(topNContext),
  scheduleDayOfMonth: scheduleDayContext === undefined ? undefined : String(scheduleDayContext),
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION ?? "ap-northeast-1",
  },
});
