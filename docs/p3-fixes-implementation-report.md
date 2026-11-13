# UnFire P3修正の実装・検証報告

2026年11月13日（JST）。ブランチ：`fix/solveP3Issue`。着手時HEAD：`d231809`（P2Issue完了）、作業ツリーに変更なし。
対象は総合監査報告のP3 2件（AUD-10・11）。P1・P2の修正を基準として保持し、コミット・プッシュ・PR作成・マージは行っていない。

## 修正結果

| ID | 原因と修正内容 | 変更ファイル | 検証結果 |
|---|---|---|---|
| AUD-10 | 倉庫API末尾に文字化けを含む旧threshold実装が、実行されない三重引用符の文字列として残っていた。履歴を照合し、その文字列51行と前の空行だけを削除 | `app/routes/warehouses.py` | 文字列式を除いた削除前ASTと削除後ASTが一致。別プロセスで生成した全72ルートのパス・endpoint・HTTPメソッドも一致。既存API回帰を実行 |
| AUD-11 | CIがpytestだけを実行し、画面JSの回帰試験とNode版を明示していなかった。Node.js 24.19.0のセットアップと全`tests/*.test.cjs`の実行を追加 | `.github/workflows/tests.yml`、`README.md` | CI用コマンドで8ファイル・71件成功。隔離した一時テスト2件のうち1件を意図的に失敗させ、終了コード1を確認。Pythonからの実JS・HTTP連携も回帰対象 |

対象2件はコード修正・ローカル検証を実施。GitHub上のworkflow実行は未実施のため、リモートCI成功とは報告しない。

## 採用範囲と確認根拠

- `docs/reviews/UnFire_Final_Audit.md`のAUD-10・11、ルート`AGENTS.md`、`write-tests`手順を適用。
- `git log`と`git show`で倉庫APIの旧履歴を確認し、実行中のAPI1.0実装と旧文字列を区別した。業務・API・画面・DB仕様は変更していない。
- Node.jsはP2で検証した24.19.0を明示採用。新規のnpm依存やブラウザ基盤は追加していない。
- Nodeセットアップはpytestより前に配置。P1・P2の実JS→HTTP→隔離SQLite連携でも同じNodeを使う。Python版、依存関係、`develop`向けPRという既存トリガーは維持。
- JS実行を`node --test "tests/*.test.cjs"`へ統一。将来追加する同形式のテストも対象になる。専用サーバーURLが必要な`p1-ui-api-flow.cjs`・`p2-ui-api-flow.cjs`はpytest側から実行する。
- `actions/setup-node@v7`の入力とバージョン指定は[公式setup-node資料](https://github.com/actions/setup-node)を確認。npmキャッシュは不要なので無効化。引用符付きglobは[Node.js 24の公式テストランナー資料](https://nodejs.org/docs/latest-v24.x/api/test.html#running-tests-from-the-command-line)に合わせ、シェルによる展開に依存させない。

## 検証

実行場所：リポジトリルート。環境：Windows／PowerShell、Python 3.15.2、Node.js v24.19.0。

| 確認 | 結果 |
|---|---|
| 既存Pythonテスト全件 | 553件成功、失敗0、エラー0、skip0（49.26秒）。P1・P2と実JS・HTTP連携を含む |
| CI用JSコマンド | 71件成功、失敗0、skip0。終了コード0 |
| 失敗の伝播 | 一時テスト2件（成功1・意図的失敗1）、終了コード1。実際のリポジトリテストの失敗ではない。一時ファイルは削除済み |
| 実行部分の不変 | AST一致、全72ルート一致。比較のためのアプリ生成ではDBに接続せず、新規DBも作成していない |
| 差分 | `git diff --check`成功。アプリ側の変更は末尾の非実行文字列削除だけ |
| DDL | 正本と実行用SQLは変更なし。SHA-256はともに`f7ae51da54d710414639429d120a62bbb13cf8f42131fce7d6ad40b7c5c55698` |

```powershell
node --test "tests/*.test.cjs"
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-p3-regression -p no:cacheprovider
```

子プロセス生成とpytest一時領域に対する既知のサンドボックス制限を避け、権限付きで実行した。DB更新は既存fixtureの隔離DBだけで、開発・共有DBを使っていない。
低影響の整理に実装をなぞる恒久テストは追加せず、既存の正常・異常・境界・原子性・履歴不変テストを再利用した。

## 残る確認と対象外

- GitHub ActionsのUbuntu runnerでの実行は、変更を共有した後に確認が必要。今回はローカルコマンドの成功、workflowの差分・配置確認まで。
- P3で画面変更はない。P1・P2報告に残る実ブラウザでの描画・操作確認を、今回実施済みとは扱わない。
- 人間による差分レビュー・受入は別途必要。新たな仕様判断待ちはない。
- 監査報告は過去の監査時点の記録として保持した。他機能の整理、API契約・DB構造の変更、他のActionsの更新は対象外。
