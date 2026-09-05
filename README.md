# Flyers — ボカブキ フライヤー収集

ボカブキ（Vocaloid club night, Tokyo）の2周年（2026-09-26）に向けて、2025-08-01〜2026-09-30 の
ホリデーイベント全ての集客用フライヤー画像を収集・管理するための、ビルド不要の静的サイトです。

カレンダー形式で全イベントを一覧し、フライヤー画像が保存済みかどうかを一目で確認でき、
オーナーがツイート（X）のURLと画像を保存できます。UI は日本語です。

## 使っているもの

- `index.html` — 単一ページのアプリ本体（Vanilla JS + CSS、フレームワークなし）。
- `data/events.json` — イベントデータ（下記スクリプトで生成・更新）。
- `images/` — 保存されたフライヤー画像（`images/<event id>.<ext>`）。
- `scripts/ics_to_events.py` / `scripts/gcal_to_events.py` — 外部カレンダーのデータを
  `data/events.json` にマージするスクリプト。

## バージョン表示

ヘッダー右上の `ver.N` は `index.html` 内の `APP_VERSION` の値です。**main にマージするごとに +1** します
（ver.1 = 初回リリース PR #1）。

## GitHub Pages の有効化

1. GitHub のリポジトリ設定 → **Pages** を開く。
2. Source を「Deploy from a branch」にし、ブランチ（例: `main`）とルート（`/`）を選択して保存。
3. 数分後に `https://<owner>.github.io/<repo>/` で公開されます（`.nojekyll` により Jekyll 処理はスキップされます）。

## GitHub トークンの設定（フライヤー保存に必要）

このサイトは静的ホスティングのため、保存操作は GitHub の Contents API を直接ブラウザから叩きます。

1. GitHub で **Fine-grained personal access token** を発行:
   - 対象リポジトリ: このリポジトリのみ
   - 権限: **Contents: Read and write**
2. サイト右上の歯車アイコン（設定）を開き、トークン・Owner・リポジトリ名・ブランチを入力して保存。
   - デフォルト値は `vocabuki-io` / `Flyers` / `main`。実際のリポジトリに合わせて変更してください。
   - トークンはこの端末の `localStorage` にのみ保存され、どこにも送信されません。
3. 以後、イベントの保存・画像アップロード・追加・削除がすべてこのトークンで GitHub 上のファイルを
   直接更新します（コミットが作られます）。GitHub Pages の反映には最大1分程度かかることがあります
   （保存直後はローカルプレビューで表示され続けます）。

## カレンダーからのデータ更新方法

イベントデータは2つのソースを `data/events.json` にマージして作られています。

### 1. TimeTree（2025-08〜2026-05 のシフト表、`休日営業`/`平日営業` カテゴリのみ）

1. TimeTree からカレンダーを `.ics` 形式でエクスポートし、`data/timetree_export.ics` として保存。
2. 実行:
   ```
   python3 scripts/ics_to_events.py data/timetree_export.ics
   ```
   - `休日営業` と `平日営業` カテゴリのイベントのみ取り込みます（スタッフシフト等の他カテゴリは無視）。
   - 2026-06-01 以降の日付は無視します（そこから先は Google カレンダー側のデータを使うため）。
   - `holiday` は開催日が金曜または土曜かどうかで自動判定されます（他の曜日は `holiday: false` で
     取り込まれ、サイト上のスイッチで個別に変更できます）。
   - 既存の `data/events.json` があれば `icsUid`（ICS の UID）でマッチさせてマージし、
     オーナーが編集した `tweetUrl` / `image` / `note` / `holiday` は上書きしません。
   - RRULE（繰り返し予定）を持つイベントは展開せずスキップし、警告を表示します。

### 2. Google カレンダー（2026-06〜の本予定）

1. Google Calendar API の `events.list` で取得した JSON を `data/gcal_export.json` として保存。
2. 実行:
   ```
   python3 scripts/gcal_to_events.py data/gcal_export.json
   ```
   - `[タスク]` で始まる予定と終日予定はスキップします。
   - `holiday` は開催日が金曜または土曜かどうかで自動判定されます。
   - 既存の `data/events.json` があれば `gcalId` でマッチさせてマージし、オーナーの編集内容は保持します。

### 実行順序

初期データ作成・再構築時は **先に ICS、その後に Google カレンダー** の順で実行してください
（どちらのスクリプトも他ソースのイベントには触れないため、順序を変えても壊れることはありませんが、
このリポジトリのコミット履歴はこの順で作られています）。

```
python3 scripts/ics_to_events.py data/timetree_export.ics
python3 scripts/gcal_to_events.py data/gcal_export.json
```

2025-08〜2026-05 のバックフィル分（TimeTree に無いイベントなど）はサイト右下の
「イベント追加」から手動（`source: "manual"`）で追加してください。
