# AWS 月次コストレポート メール通知システム 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cost Explorer API で前月のコスト明細を取得し、毎月5日 09:00 JST に SNS 経由でメール通知する仕組みを AWS CDK (TypeScript) で構築する。

**Architecture:** EventBridge Rule が Lambda (Python) を月次で非同期起動する。Lambda は Cost Explorer から前月・前々月の2ヶ月分を1リクエストで取得し、プレーンテキストのレポートを組み立てて SNS トピックへ Publish する。SNS の Email サブスクリプションがメールを配信する。失敗時も同じトピックへエラー通知を1通送る。

**Tech Stack:** AWS CDK v2 (TypeScript), Lambda Python 3.13, boto3 (ランタイム同梱), Amazon SNS, Amazon EventBridge, pytest, Jest + ts-jest

**Spec:** `docs/superpowers/specs/2026-08-08-aws-monthly-cost-report-design.md`

## Global Constraints

- Lambda ランタイムは `Runtime.PYTHON_3_13`。ただし**ローカルの Python は 3.10** なので、Lambda 本体・テストとも Python 3.10 で動作する構文に限定する（`match` 文、`X | Y` 形式の型注釈、`typing` の 3.11+ 機能を使わない）。型注釈は `typing` モジュール（`Dict`, `List`, `Optional`, `NamedTuple`）を使う。
- Lambda の外部依存はゼロ。`boto3` / `botocore` のみ使用し、`requirements.txt` によるバンドルは行わない。
- 金額は必ず `decimal.Decimal` で保持する。`float` に変換しない。表示時のみ `quantize` で丸める。
- Cost Explorer クライアントは `region_name="us-east-1"` を明示する（CE のエンドポイントは us-east-1 固定）。
- boto3 クライアントには `Config(retries={"mode": "standard", "max_attempts": 5})` を設定する。
- SNS の `Subject` は **ASCII のみ、改行なし、100 文字未満**。日本語は本文（`Message`）にのみ使う。
- CDK スタックの `env` は `process.env.CDK_DEFAULT_ACCOUNT` / `process.env.CDK_DEFAULT_REGION ?? "ap-northeast-1"`。アカウント ID をソースに書かない。
- 通知先メールアドレスは CDK context `notifyEmail` から取得する。ソースに埋め込まない。
- Lambda 実行ロールの権限は `ce:GetCostAndUsage` (`*`)、`sns:Publish`（本スタックのトピック ARN のみ）、`AWSLambdaBasicExecutionRole` 相当のログ3アクションのみ。
- コミットは Conventional Commits 形式（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）。
- 全ファイルは UTF-8。

---

## File Structure

| パス | 責務 |
|---|---|
| `package.json` | npm スクリプトと依存 |
| `tsconfig.json` | TypeScript 設定 |
| `cdk.json` | CDK アプリのエントリポイント指定 |
| `jest.config.js` | CDK スタックテストの設定 |
| `pytest.ini` | pytest の `pythonpath` 設定 |
| `bin/app.ts` | CDK App。context 検証と env 解決 |
| `lib/aws-monthly-cost-report-stack.ts` | 全 AWS リソースの定義 |
| `lambda/cost_report/periods.py` | 期間計算（純粋関数） |
| `lambda/cost_report/cost_explorer.py` | CE 呼び出しとレスポンス正規化 |
| `lambda/cost_report/formatter.py` | 件名・本文の生成（純粋関数） |
| `lambda/cost_report/notifier.py` | SNS Publish と Subject のサニタイズ |
| `lambda/cost_report/handler.py` | オーケストレーションとエラーハンドリング |
| `tests/python/test_*.py` | Lambda 各モジュールの pytest |
| `test/aws-monthly-cost-report-stack.test.ts` | CDK スタックの assertions テスト |
| `README.md` | デプロイ・確認・削除手順 |

---

## Task 1: プロジェクト骨組み

**Files:**
- Create: `package.json`, `tsconfig.json`, `cdk.json`, `jest.config.js`, `pytest.ini`
- Create: `lambda/cost_report/__init__.py`
- Create: `tests/python/__init__.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: なし
- Produces: `npm run build`, `npm test`, `pytest` が実行可能な状態。`pytest.ini` の `pythonpath = lambda` により、テストから `from cost_report import ...` でインポートできる。

- [ ] **Step 1: `package.json` を作成する**

```json
{
  "name": "aws-monthly-cost-report",
  "version": "0.1.0",
  "private": true,
  "bin": {
    "aws-monthly-cost-report": "bin/app.js"
  },
  "scripts": {
    "build": "tsc",
    "watch": "tsc -w",
    "test": "jest",
    "cdk": "cdk"
  },
  "devDependencies": {
    "@types/jest": "^29.5.14",
    "@types/node": "^22.10.2",
    "aws-cdk": "^2.1035.0",
    "jest": "^29.7.0",
    "ts-jest": "^29.2.5",
    "ts-node": "^10.9.2",
    "typescript": "~5.6.3"
  },
  "dependencies": {
    "aws-cdk-lib": "^2.263.0",
    "constructs": "^10.4.2"
  }
}
```

- [ ] **Step 2: `tsconfig.json` を作成する**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "lib": ["es2022"],
    "declaration": true,
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "inlineSourceMap": true,
    "inlineSources": true,
    "experimentalDecorators": true,
    "strictPropertyInitialization": false,
    "typeRoots": ["./node_modules/@types"]
  },
  "exclude": ["node_modules", "cdk.out"]
}
```

- [ ] **Step 3: `cdk.json` を作成する**

```json
{
  "app": "npx ts-node --prefer-ts-exts bin/app.ts",
  "watch": {
    "include": ["**"],
    "exclude": ["README.md", "cdk*.json", "**/*.d.ts", "**/*.js", "tsconfig.json", "package*.json", "yarn.lock", "node_modules", "test", "tests", "docs"]
  },
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:checkSecretUsage": true,
    "@aws-cdk/core:target-partitions": ["aws", "aws-cn"],
    "@aws-cdk/aws-iam:minimizePolicies": true,
    "@aws-cdk/core:validateSnapshotRemovalPolicy": true
  }
}
```

- [ ] **Step 4: `jest.config.js` を作成する**

```js
module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": "ts-jest",
  },
};
```

- [ ] **Step 5: `pytest.ini` を作成する**

`pythonpath` により `lambda/` ディレクトリがインポートパスに入り、テストから `cost_report` パッケージを読める。

```ini
[pytest]
pythonpath = lambda
testpaths = tests/python
```

- [ ] **Step 6: 空のパッケージファイルを作成する**

`lambda/cost_report/__init__.py` と `tests/python/__init__.py` を**空ファイル**として作成する。

- [ ] **Step 7: `.gitignore` を更新する**

既存の `.gitignore` を以下の内容で上書きする。

```gitignore
node_modules/
cdk.out/
*.js
*.d.ts
!jest.config.js
__pycache__/
.pytest_cache/
*.pyc
.venv/
```

- [ ] **Step 8: 依存をインストールしてツールチェーンを検証する**

Run:
```bash
npm install
npx tsc --version
python3 -m pytest --version
```
Expected: いずれもエラーなくバージョンが表示される。`python3 -m pytest` が「No module named pytest」で失敗する場合は `python3 -m pip install --user pytest` を実行する。

- [ ] **Step 9: コミット**

```bash
git add package.json package-lock.json tsconfig.json cdk.json jest.config.js pytest.ini .gitignore lambda tests
git commit -m "chore: CDK + pytest プロジェクトの骨組みを追加"
```

---

## Task 2: 期間計算モジュール (`periods.py`)

**Files:**
- Create: `lambda/cost_report/periods.py`
- Test: `tests/python/test_periods.py`

**Interfaces:**
- Consumes: なし（標準ライブラリのみ）
- Produces:
  - `class ReportPeriod(NamedTuple)` — フィールド: `target_start: date`, `target_end: date`, `previous_start: date`, `previous_end: date`, `query_start: date`, `query_end: date`
  - `def build_report_period(today: date) -> ReportPeriod`
  - `ReportPeriod.target_label` プロパティ — `"2026-07"` 形式の文字列を返す

- [ ] **Step 1: 失敗するテストを書く**

`tests/python/test_periods.py`:

```python
from datetime import date

from cost_report.periods import build_report_period


def test_通常月_前月と前々月を返す():
    period = build_report_period(date(2026, 8, 5))

    assert period.target_start == date(2026, 7, 1)
    assert period.target_end == date(2026, 7, 31)
    assert period.previous_start == date(2026, 6, 1)
    assert period.previous_end == date(2026, 6, 30)


def test_通常月_CEクエリ範囲は前々月1日から当月1日まで():
    period = build_report_period(date(2026, 8, 5))

    assert period.query_start == date(2026, 6, 1)
    assert period.query_end == date(2026, 8, 1)


def test_1月実行時は年をまたいで前年12月と11月を返す():
    period = build_report_period(date(2026, 1, 5))

    assert period.target_start == date(2025, 12, 1)
    assert period.target_end == date(2025, 12, 31)
    assert period.previous_start == date(2025, 11, 1)
    assert period.previous_end == date(2025, 11, 30)
    assert period.query_start == date(2025, 11, 1)
    assert period.query_end == date(2026, 1, 1)


def test_うるう年の2月を対象月として正しく扱う():
    period = build_report_period(date(2024, 3, 5))

    assert period.target_start == date(2024, 2, 1)
    assert period.target_end == date(2024, 2, 29)
    assert period.previous_start == date(2024, 1, 1)
    assert period.previous_end == date(2024, 1, 31)


def test_月初1日に実行しても前月が対象になる():
    period = build_report_period(date(2026, 8, 1))

    assert period.target_start == date(2026, 7, 1)
    assert period.target_end == date(2026, 7, 31)


def test_target_labelはYYYY_MM形式を返す():
    period = build_report_period(date(2026, 8, 5))

    assert period.target_label == "2026-07"
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 -m pytest tests/python/test_periods.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cost_report.periods'`

- [ ] **Step 3: 最小の実装を書く**

`lambda/cost_report/periods.py`:

```python
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
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `python3 -m pytest tests/python/test_periods.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: コミット**

```bash
git add lambda/cost_report/periods.py tests/python/test_periods.py
git commit -m "feat: レポート対象期間の計算モジュールを追加"
```

---

## Task 3: Cost Explorer 呼び出しモジュール (`cost_explorer.py`)

**Files:**
- Create: `lambda/cost_report/cost_explorer.py`
- Test: `tests/python/test_cost_explorer.py`

**Interfaces:**
- Consumes: `cost_report.periods.ReportPeriod`
- Produces:
  - `METRIC = "UnblendedCost"`
  - `DEFAULT_UNIT = "USD"`
  - `class MonthlyCost(NamedTuple)` — `period_start: date`, `total: Decimal`, `by_service: Dict[str, Decimal]`, `unit: str`
  - `def fetch_monthly_costs(client, period: ReportPeriod) -> Dict[date, MonthlyCost]`
  - `def get_month(costs: Dict[date, MonthlyCost], period_start: date) -> MonthlyCost` — 該当月がなければ合計0の空 `MonthlyCost` を返す

**設計上の要点:**
- 2ヶ月分を1リクエストで取得する（`ResultsByTime` が2要素返る）。
- `NextPageToken` がある限りループする。同じ `TimePeriod` が複数ページにまたがるため、月キーで**加算**して集約する。
- 金額 0 のサービスは `by_service` から除外する。
- `total` は `by_service` の合計。`GroupBy` 指定時は CE の `Total` フィールドが空になるため、グループを合算する必要がある。

- [ ] **Step 1: 失敗するテストを書く**

`tests/python/test_cost_explorer.py`:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 -m pytest tests/python/test_cost_explorer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cost_report.cost_explorer'`

- [ ] **Step 3: 最小の実装を書く**

`lambda/cost_report/cost_explorer.py`:

```python
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
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `python3 -m pytest tests/python/test_cost_explorer.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: コミット**

```bash
git add lambda/cost_report/cost_explorer.py tests/python/test_cost_explorer.py
git commit -m "feat: Cost Explorer からのコスト取得と正規化を追加"
```

---

## Task 4: 本文フォーマットモジュール (`formatter.py`)

**Files:**
- Create: `lambda/cost_report/formatter.py`
- Test: `tests/python/test_formatter.py`

**Interfaces:**
- Consumes: `cost_report.periods.ReportPeriod`, `cost_report.cost_explorer.MonthlyCost`
- Produces:
  - `DEFAULT_TOP_N = 10`
  - `def build_subject(period, target: MonthlyCost, previous: MonthlyCost) -> str` — ASCII のみ
  - `def build_body(period, target, previous, account_id: str, top_n: int = DEFAULT_TOP_N) -> str`
  - `def build_error_subject() -> str` — ASCII のみ
  - `def build_error_body(period, error: BaseException, request_id: str) -> str`

**設計上の要点:**
- 件名は SNS の ASCII 制約に従い英語。本文は日本語。
- 全角文字を含む行の桁揃えのため、`unicodedata.east_asian_width` で表示幅を数える `_pad` を使う。
- 前月合計が 0 のときは変化率を出さない（ゼロ除算回避）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/python/test_formatter.py`:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 -m pytest tests/python/test_formatter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cost_report.formatter'`

- [ ] **Step 3: 最小の実装を書く**

`lambda/cost_report/formatter.py`:

```python
"""メールの件名と本文の組み立て。AWS に依存しない純粋関数のみ。

SNS の Subject は ASCII のみ・100文字未満という制約があるため、件名は英語で組み立てる。
Message（本文）には制約がないので日本語で記述する。
"""

import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict

from .cost_explorer import MonthlyCost
from .periods import ReportPeriod

DEFAULT_TOP_N = 10
_NAME_WIDTH = 28
_AMOUNT_WIDTH = 9
_RANK_PREFIX_WIDTH = 5  # " NN. " の表示幅
_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")
_SEPARATOR = "=" * 44
_FOOTER = "--\nGenerated by aws-monthly-cost-report"


def visual_width(text: str) -> int:
    """等幅フォントでの表示幅。全角文字を2桁として数える。"""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def _pad(text: str, width: int) -> str:
    """表示幅を基準に右側を空白で埋める。"""
    return text + " " * max(width - visual_width(text), 0)


def _amount(value: Decimal) -> str:
    return "{:.2f}".format(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _signed_amount(value: Decimal) -> str:
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    sign = "+" if rounded >= 0 else "-"
    return "{}{:.2f}".format(sign, abs(rounded))


def _percentage(current: Decimal, previous: Decimal):
    """変化率。前月が 0 のときは計算できないので None を返す。"""
    if previous == 0:
        return None
    rounded = ((current - previous) / previous * 100).quantize(_TENTH, rounding=ROUND_HALF_UP)
    sign = "+" if rounded >= 0 else "-"
    return "{}{:.1f}%".format(sign, abs(rounded))


def build_subject(period: ReportPeriod, target: MonthlyCost, previous: MonthlyCost) -> str:
    """ASCII のみの件名を返す。"""
    parts = [
        "[AWS Cost]",
        period.target_label,
        "total",
        _amount(target.total),
        target.unit,
    ]
    percentage = _percentage(target.total, previous.total)
    if percentage is not None:
        parts.append("({})".format(percentage))
    return " ".join(parts)


def build_error_subject() -> str:
    """ASCII のみのエラー件名を返す。"""
    return "[AWS Cost][ERROR] monthly cost report failed"


def _service_lines(target: MonthlyCost, previous: MonthlyCost, top_n: int):
    if not target.by_service:
        return ["  対象期間のコストデータがありません。"]

    ranked = sorted(target.by_service.items(), key=lambda item: item[1], reverse=True)
    lines = []

    for rank, (service, amount) in enumerate(ranked[:top_n], start=1):
        delta = amount - previous.by_service.get(service, Decimal(0))
        lines.append(
            " {:>2}. {} {:>{width}} {}  ({})".format(
                rank,
                _pad(service, _NAME_WIDTH),
                _amount(amount),
                target.unit,
                _signed_amount(delta),
                width=_AMOUNT_WIDTH,
            )
        )

    remainder = ranked[top_n:]
    if remainder:
        subtotal = sum((amount for _, amount in remainder), Decimal(0))
        label = "その他 ({}件)".format(len(remainder))
        lines.append(
            "{}{} {:>{width}} {}".format(
                " " * _RANK_PREFIX_WIDTH,
                _pad(label, _NAME_WIDTH),
                _amount(subtotal),
                target.unit,
                width=_AMOUNT_WIDTH,
            )
        )

    return lines


def build_body(
    period: ReportPeriod,
    target: MonthlyCost,
    previous: MonthlyCost,
    account_id: str,
    top_n: int = DEFAULT_TOP_N,
) -> str:
    """レポート本文（日本語プレーンテキスト）を組み立てる。"""
    percentage = _percentage(target.total, previous.total)
    delta_suffix = (
        "({})".format(percentage) if percentage is not None else "(前月 0.00 のため率は非表示)"
    )

    lines = [
        _SEPARATOR,
        " AWS 月次コストレポート",
        _SEPARATOR,
        "アカウント : {}".format(account_id),
        "対象期間   : {} 〜 {}".format(period.target_start.isoformat(), period.target_end.isoformat()),
        "",
        "■ 合計",
        "  当月    : {} {}".format(_amount(target.total), target.unit),
        "  前月    : {} {}".format(_amount(previous.total), previous.unit),
        "  差分    : {} {} {}".format(
            _signed_amount(target.total - previous.total), target.unit, delta_suffix
        ),
        "",
        "■ サービス別内訳 (上位{}件 / UnblendedCost)".format(top_n),
    ]
    lines.extend(_service_lines(target, previous, top_n))
    lines.extend(["", _FOOTER])

    return "\n".join(lines)


def build_error_body(period: ReportPeriod, error: BaseException, request_id: str) -> str:
    """エラー通知の本文（日本語プレーンテキスト）を組み立てる。

    スタックトレースはメールに載せず CloudWatch Logs に残す。
    """
    lines = [
        _SEPARATOR,
        " AWS 月次コストレポート / エラー",
        _SEPARATOR,
        "月次コストレポートの生成に失敗しました。",
        "",
        "対象期間     : {} 〜 {}".format(
            period.target_start.isoformat(), period.target_end.isoformat()
        ),
        "エラー種別   : {}".format(type(error).__name__),
        "エラー内容   : {}".format(error),
        "リクエストID : {}".format(request_id),
        "",
        "詳細は CloudWatch Logs を確認してください。",
        "",
        _FOOTER,
    ]
    return "\n".join(lines)
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `python3 -m pytest tests/python/test_formatter.py -v`
Expected: PASS（12 passed）

失敗する場合は、期待文字列側ではなく実装の桁揃え定数（`_NAME_WIDTH`, `_AMOUNT_WIDTH`）を疑う。テストは「1件目の行の金額部分までの表示幅」と「その他行の表示幅」が一致することを検証しているので、`_pad` が表示幅ベースになっていれば揃う。

- [ ] **Step 5: コミット**

```bash
git add lambda/cost_report/formatter.py tests/python/test_formatter.py
git commit -m "feat: メール件名と本文のフォーマッタを追加"
```

---

## Task 5: SNS 通知モジュール (`notifier.py`)

**Files:**
- Create: `lambda/cost_report/notifier.py`
- Test: `tests/python/test_notifier.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `MAX_SUBJECT_LENGTH = 99`
  - `def publish(client, topic_arn: str, subject: str, message: str) -> None`
  - `def sanitize_subject(subject: str) -> str` — 非 ASCII 文字を `?` に、改行・制御文字を空白に置換し、99 文字に切り詰める

**設計上の要点:** `formatter` は ASCII 件名しか生成しないが、`sanitize_subject` を最後の防波堤として置く。ここが無いと、将来サービス名などを件名に含めた際に SNS が `InvalidParameter` を返して**エラー通知すら送れなくなる**。

- [ ] **Step 1: 失敗するテストを書く**

`tests/python/test_notifier.py`:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 -m pytest tests/python/test_notifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cost_report.notifier'`

- [ ] **Step 3: 最小の実装を書く**

`lambda/cost_report/notifier.py`:

```python
"""SNS への通知。

SNS の Subject は「ASCII テキスト」「改行・制御文字なし」「100文字未満」という制約がある。
制約違反は InvalidParameter となり Publish 自体が失敗するため、送信直前に必ずサニタイズする。
"""

MAX_SUBJECT_LENGTH = 99
_ELLIPSIS = "..."


def sanitize_subject(subject: str) -> str:
    """SNS の Subject 制約を満たす文字列に変換する。"""
    characters = []
    for char in subject:
        code = ord(char)
        if char in ("\n", "\r", "\t") or code < 0x20 or code == 0x7F:
            characters.append(" ")
        elif code > 0x7F:
            characters.append("?")
        else:
            characters.append(char)

    sanitized = "".join(characters).strip()
    if len(sanitized) <= MAX_SUBJECT_LENGTH:
        return sanitized
    return sanitized[: MAX_SUBJECT_LENGTH - len(_ELLIPSIS)] + _ELLIPSIS


def publish(client, topic_arn: str, subject: str, message: str) -> None:
    """SNS トピックへメッセージを送信する。"""
    client.publish(
        TopicArn=topic_arn,
        Subject=sanitize_subject(subject),
        Message=message,
    )
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `python3 -m pytest tests/python/test_notifier.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: コミット**

```bash
git add lambda/cost_report/notifier.py tests/python/test_notifier.py
git commit -m "feat: SNS 通知モジュールを追加"
```

---

## Task 6: Lambda ハンドラ (`handler.py`)

**Files:**
- Create: `lambda/cost_report/handler.py`
- Test: `tests/python/test_handler.py`

**Interfaces:**
- Consumes: `periods.build_report_period`, `cost_explorer.fetch_monthly_costs` / `get_month`, `formatter.*`, `notifier.publish`
- Produces:
  - `CE_REGION = "us-east-1"`
  - `def build_ce_client()` / `def build_sns_client()` — テストで monkeypatch する差し替え点
  - `def lambda_handler(event, context) -> Dict[str, str]`

**設計上の要点（最重要）:**
- 例外時はエラー通知を**1通だけ**送って再送出する。Lambda 側の `retryAttempts` を 0 にすることで重複送信を防ぐ（Task 7）。
- エラー通知の Publish 自体が失敗しても、元の例外を握り潰さない。
- `SNS_TOPIC_ARN` はハンドラ冒頭で読む。未設定なら通知先が無いので `KeyError` をそのまま送出する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/python/test_handler.py`:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 -m pytest tests/python/test_handler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cost_report.handler'`

- [ ] **Step 3: 最小の実装を書く**

`lambda/cost_report/handler.py`:

```python
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
    top_n = int(os.environ.get("TOP_N_SERVICES", str(formatter.DEFAULT_TOP_N)))

    period = periods.build_report_period(_today())
    sns_client = build_sns_client()

    try:
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
```

- [ ] **Step 4: テストを実行して成功を確認する**

Run: `python3 -m pytest tests/python/test_handler.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Python テスト全体を実行する**

Run: `python3 -m pytest -v`
Expected: PASS（32 passed）

- [ ] **Step 6: コミット**

```bash
git add lambda/cost_report/handler.py tests/python/test_handler.py
git commit -m "feat: Lambda ハンドラとエラーハンドリングを追加"
```

---

## Task 7: CDK スタック定義

**Files:**
- Create: `lib/aws-monthly-cost-report-stack.ts`
- Create: `bin/app.ts`
- Test: `test/aws-monthly-cost-report-stack.test.ts`

**Interfaces:**
- Consumes: `lambda/` ディレクトリ（`Code.fromAsset` で同梱）
- Produces:
  - `interface AwsMonthlyCostReportStackProps extends StackProps` — `notifyEmail: string`, `topNServices?: number`, `scheduleDayOfMonth?: string`
  - `class AwsMonthlyCostReportStack extends Stack` — 読み取り用に `readonly topic: sns.Topic` と `readonly reportFunction: lambda.Function` を公開する

- [ ] **Step 1: 失敗するテストを書く**

`test/aws-monthly-cost-report-stack.test.ts`:

```typescript
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
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `npx jest -t "SNS トピック"`
Expected: FAIL — `Cannot find module '../lib/aws-monthly-cost-report-stack'`

- [ ] **Step 3: スタックを実装する**

`lib/aws-monthly-cost-report-stack.ts`:

```typescript
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
      code: lambda.Code.fromAsset(path.join(__dirname, "..", "lambda")),
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
```

- [ ] **Step 4: `bin/app.ts` を実装する**

```typescript
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
```

- [ ] **Step 5: テストとビルドを実行して成功を確認する**

Run: `npm run build && npm test`
Expected: `tsc` がエラーなく完了し、Jest が 9 passed。

`AWS::Lambda::EventInvokeConfig` のテストが失敗する場合は、`retryAttempts: 0` が指定されているか確認する（CDK は `retryAttempts` 指定時にこのリソースを生成する）。

- [ ] **Step 6: synth が通ることを確認する**

Run: `npx cdk synth -c notifyEmail=test@example.com --quiet`
Expected: エラーなく完了する（AWS 認証情報は不要）。

Run: `npx cdk synth --quiet`
Expected: FAIL — `context 'notifyEmail' が指定されていません` というエラーで停止する。

- [ ] **Step 7: コミット**

```bash
git add lib bin test
git commit -m "feat: Lambda/EventBridge/SNS/IAM を定義する CDK スタックを追加"
```

---

## Task 8: README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: Task 1〜7 の全成果物
- Produces: なし

- [ ] **Step 1: `README.md` を作成する**

以下の内容を書く。コマンドは実際に Task 1〜7 で動作確認したものと一致させること。

````markdown
# aws-monthly-cost-report

AWS Cost Explorer から前月のコスト明細を取得し、毎月1回メールで通知する仕組み。AWS CDK (TypeScript) で管理する。

## 構成

| リソース | 役割 |
|---|---|
| EventBridge Rule | 毎月5日 00:00 UTC（= 09:00 JST）に Lambda を起動 |
| Lambda (Python 3.13) | Cost Explorer からコストを取得し、レポートを組み立てて SNS へ送信 |
| SNS Topic + Email Subscription | メール配信 |
| IAM Role | Lambda 実行用の最小権限ロール |

正常時のレポートも失敗時のエラー通知も、同じ SNS トピックから届く。

## 前提

- Node.js 20 以上、Python 3.10 以上（ローカルテスト用）
- AWS CLI の認証情報が設定済みであること
- **ルートユーザーで「IAM ユーザー/ロールによる請求情報へのアクセス」が有効化されていること**（Billing コンソール → Account Settings → IAM Access）。これが無効だと Lambda が `AccessDeniedException` になる。

## デプロイ

```bash
npm ci

# 初回のみ: 対象アカウント・リージョンで CDK をブートストラップ
npx cdk bootstrap

# デプロイ（notifyEmail は必須）
npx cdk deploy -c notifyEmail=you@example.com
```

デプロイ先のアカウント・リージョンは AWS CLI のプロファイルに従う。切り替える場合:

```bash
npx cdk deploy --profile my-profile -c notifyEmail=you@example.com
```

リージョンを明示する場合:

```bash
CDK_DEFAULT_REGION=us-east-1 npx cdk deploy -c notifyEmail=you@example.com
```

リージョン未指定時の既定は `ap-northeast-1`。なお Cost Explorer API はどのリージョンにデプロイしても `us-east-1` に対して呼び出される（コード内で固定）。

### 任意のオプション

| context | 既定値 | 説明 |
|---|---|---|
| `notifyEmail` | （必須） | 通知先メールアドレス |
| `topNServices` | `10` | サービス別内訳に列挙する件数 |
| `scheduleDayOfMonth` | `5` | 実行日（毎月の日付） |

例: `npx cdk deploy -c notifyEmail=you@example.com -c topNServices=5 -c scheduleDayOfMonth=3`

## SNS サブスクリプションの確認（手動作業）

デプロイ直後、指定したメールアドレス宛に AWS から確認メールが届く。**この承認を行うまでメールは配信されない。**

1. 件名 `AWS Notification - Subscription Confirmation` のメールを開く
2. 本文中の **Confirm subscription** リンクをクリックする
3. ブラウザに `Subscription confirmed!` と表示されれば完了

状態を確認する:

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn "$(aws cloudformation describe-stacks \
      --stack-name AwsMonthlyCostReportStack \
      --query 'Stacks[0].Outputs' --output text 2>/dev/null || true)"
```

より簡単には、SNS コンソールでトピック `AWS Monthly Cost Report` を開き、サブスクリプションの Status が `Confirmed` になっていることを確認する。`PendingConfirmation` のままなら確認メールのリンクが未クリック。

確認メールが見つからない場合は迷惑メールフォルダを確認し、それでも無ければ SNS コンソールから **Request confirmation** を再送する。

## 動作確認（手動実行）

スケジュールを待たずにテストする:

```bash
FUNCTION_NAME=$(aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName, 'AwsMonthlyCostReportStack-CostReportFunction')].FunctionName | [0]" \
  --output text)

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/cost-report-response.json

cat /tmp/cost-report-response.json
```

`{"status": "ok", "period": "YYYY-MM"}` が返り、数分以内にメールが届けば成功。

ログを確認する:

```bash
aws logs tail "/aws/lambda/$FUNCTION_NAME" --since 10m --follow
```

## メール本文の例

```
============================================
 AWS 月次コストレポート
============================================
アカウント : 123456789012
対象期間   : 2026-07-01 〜 2026-07-31

■ 合計
  当月    : 123.45 USD
  前月    : 111.15 USD
  差分    : +12.30 USD (+11.1%)

■ サービス別内訳 (上位10件 / UnblendedCost)
  1. Amazon RDS                     45.20 USD  (+2.10)
  2. Amazon EC2 - Compute           38.10 USD  (+9.80)
  ...
     その他 (5件)                    3.15 USD

--
Generated by aws-monthly-cost-report
```

件名は SNS の制約（ASCII のみ・100 文字未満）により英語:
`[AWS Cost] 2026-07 total 123.45 USD (+11.1%)`

## 開発

```bash
npm run build          # TypeScript のコンパイル
npm test               # CDK スタックのテスト (Jest)
python3 -m pytest      # Lambda コードのテスト (pytest)
npx cdk synth -c notifyEmail=test@example.com    # CloudFormation テンプレートの生成
npx cdk diff -c notifyEmail=you@example.com      # 差分確認
```

Lambda のランタイムは Python 3.13 だが、ローカルの pytest がそのまま動くよう、コードは Python 3.10 互換の構文に留めている。

## IAM 実行ロールの権限

| アクション | リソース |
|---|---|
| `ce:GetCostAndUsage` | `*`（Cost Explorer はリソースレベル権限をサポートしないため） |
| `sns:Publish` | 本スタックが作成したトピックのみ |
| `logs:CreateLogGroup` / `logs:CreateLogStream` / `logs:PutLogEvents` | Lambda のロググループ |

## 実行日について

既定は毎月5日。3日ではなく5日にしているのは、Savings Plans / Reserved Instances の償却按分、AWS Support 料金、クレジット適用が月初1〜3日の時点では未反映または変動する場合があるため。速報値で構わない場合は `-c scheduleDayOfMonth=3` で変更できる。

## 削除

```bash
npx cdk destroy -c notifyEmail=you@example.com
```

SNS トピック、Lambda、EventBridge Rule、IAM ロール、ロググループがすべて削除される。

## コスト

- Cost Explorer API: 1リクエスト $0.01 × 月1回 = 月 $0.01
- Lambda / SNS / EventBridge / CloudWatch Logs: 無料利用枠の範囲内（月1回実行、メール1通）
````

- [ ] **Step 2: README のコマンドが正しいことを確認する**

Run: `npm run build && npm test && python3 -m pytest -q && npx cdk synth -c notifyEmail=test@example.com --quiet`
Expected: すべて成功する。

- [ ] **Step 3: コミット**

```bash
git add README.md
git commit -m "docs: デプロイ手順と SNS サブスクリプション確認手順の README を追加"
```

---

## 完了条件

- [ ] `python3 -m pytest` が全件成功する（32 tests）
- [ ] `npm test` が全件成功する（9 tests）
- [ ] `npm run build` が警告なく完了する
- [ ] `npx cdk synth -c notifyEmail=test@example.com` が成功する
- [ ] `npx cdk synth`（context 無し）が明示的なエラーで停止する
- [ ] `README.md` にデプロイ・SNS 確認・手動実行・削除の各手順が記載されている

## 実デプロイ後の検証（ユーザー作業）

CDK の合成までは AWS 認証情報なしで検証できるが、以下は実際のデプロイが必要:

1. `npx cdk deploy -c notifyEmail=<自分のメール>` を実行する
2. 確認メールの **Confirm subscription** をクリックする
3. Lambda を手動実行し、レポートメールが届くことを確認する
4. 金額がマネジメントコンソールの Cost Explorer と一致することを確認する
