# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## コマンド

```bash
npm run build                                   # tsc
npm test                                        # Jest（CDK スタックのテスト）
.venv/bin/python -m pytest                      # pytest（Lambda のテスト）
npx cdk synth -c notifyEmail=test@example.com
```

- **pytest は必ず `.venv/bin/python -m pytest` で実行する。** pytest と boto3 は `.venv` にしか入っていないため、素の `pytest` / `python3 -m pytest` は動かない。未セットアップなら `python3 -m venv .venv && .venv/bin/pip install pytest boto3`。
- **pytest はリポジトリルートから実行する。** `pytest.ini` の `pythonpath = lambda` が `from cost_report import ...` の解決を担っており、他のディレクトリからだと壊れる。
- **`test/` と `tests/` は別物。** `test/`（単数）は Jest の CDK テスト、`tests/python/` は pytest。片方を直したつもりでもう片方を見ていない事故が起きやすい。
- **cdk コマンドは全て `-c notifyEmail=...` が必須。** `synth` / `diff` / `deploy` だけでなく `destroy` にも要る。`bin/app.ts` が意図的に throw する（メール未設定のままデプロイされるのを防ぐため）。

lint / formatter は未導入。CI もない。

## 壊してはいけない不変条件

いずれも「一見冗長に見えるが消すと壊れる」もの。理由は設計書 §4.5 / §4.8 / §5.1 にある。

- **`Code.fromAsset` の `exclude: ["**/__pycache__", "**/*.pyc"]`**（`lib/aws-monthly-cost-report-stack.ts`）— 外すと、ローカルで pytest を実行したかどうかでアセットハッシュが変わり、コード無変更でも `cdk diff` に差分が出る。回帰テストあり。
- **`jest.config.js` の `moduleFileExtensions`（`ts` を `js` より先に置く）** — 外すと `npm test` が `npm run build` の出力した古い `lib/*.js` を検証する。実際にこれで「修正が効いていない」誤判定が起きた。
- **`retryAttempts: 0`（CDK 側）と boto3 の `max_attempts: 5`（Lambda 側）は対になっている。** 片方だけ変えるとエラーメールが 3 通届くか、一時障害を吸収できなくなる。
- **SNS の `Subject` は ASCII のみ・改行なし・100 文字未満。** 違反すると `InvalidParameter` で Publish 自体が失敗する。件名は英語、本文は日本語。`notifier.sanitize_subject` が最後の防波堤。

## コード規約

- **金額は必ず `decimal.Decimal` で保持する。`float` に変換しない。** 丸めは表示時のみ `quantize(_CENT, rounding=ROUND_HALF_UP)` で明示的に行う。
- **コメント・docstring・テスト名は日本語で書く。** Python のテスト関数名も日本語（`def test_1月実行時は年をまたいで前年12月と11月を返す():`）、Jest のテストタイトルも日本語。
- **Lambda コードは Python 3.10 互換の構文に留める**（`match` 文、`X | Y` 型注釈、`typing` の 3.11+ 機能を使わない。型注釈は `Dict` / `List` / `Optional` / `NamedTuple`）。理由はローカルの Python が 3.10 で、pytest をそのまま動かすため。**これは暫定措置** — ローカルが 3.13 に上がれば緩和してよい（Lambda ランタイムは 3.13）。
- **`periods.py` と `formatter.py` は AWS に依存させない。** 純粋関数に保つことで単体テストが容易になる、という設計上の分離。
- **`requirements.txt` を作らない。** boto3 は Lambda ランタイム同梱で、ローカルにはテスト用にのみ入れている。Lambda の外部依存はゼロ。
- TypeScript はダブルクォート、複数行呼び出しは末尾カンマ。

## リポジトリ規約

- **コミットは Conventional Commits。prefix は ASCII、説明は日本語**（例: `feat: SNS 通知モジュールを追加`）。スコープなし、末尾ピリオドなし。
- **ブランチは `<type>/<kebab-desc>`**（例: `feat/monthly-cost-report`）。base は `main`。今後 GitHub に上げて PR 運用に移行する予定。
- **`docs/superpowers/` は作成時点のログであり、生きたドキュメントではない。** ファイル名の日付時点の記録として扱い、後から遡って更新しない（例: 実装計画の「実デプロイ後の検証 / 未実施」は 2026-08-08 時点の記述であって、その後デプロイ済みでも直さない）。最新の状態を表す正典は `README.md` と本ファイルで、実装・手順・制約が変わったらこの 2 つを `docs:` コミットで更新する。食い違う場合は正典が正しい。
- `*.js` / `*.d.ts` は `tsc` の出力でありソースではない（`.gitignore` 済み、例外は `jest.config.js`）。`lib/` `bin/` `test/` 内のこれらを直接編集しない。

## AWS 側の前提（コードに現れない）

- Billing コンソールで「IAM ユーザー/ロールによる請求情報へのアクセス」が有効でないと、Lambda が `AccessDeniedException` になる。
- SNS の Email サブスクリプションは、デプロイ後に確認メールの **Confirm subscription** をクリックするまで配信されない。
- Cost Explorer のエンドポイントは `us-east-1` 固定（デプロイ先が `ap-northeast-1` でも）。
- アカウント ID と通知先メールアドレスをソースに書かない。CDK context と CLI プロファイルで渡す。

デプロイ手順の詳細は @README.md を参照。
