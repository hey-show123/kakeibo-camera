# 家計簿カメラ — あなたの AI で読む家計簿

iPhone のアプリ「家計簿カメラ」でレシートを撮ると、写真はあなたの iCloud Drive に入ります。
あなたの Mac の AI（Claude Code など）がこのリポジトリの手順で読み、品目・値引き・消費税まで分けて台帳（CSV）に記帳します。
記帳した数字はアプリの「お金の状況」に、カレンダー・グラフ・予算の「あと使える額」として出ます。

```
iPhone で撮る ─▶ iCloud Drive の受信箱 ─▶ Mac の AI が読んで台帳へ ─▶ 数字を受信箱へ ─▶ アプリに出る
```

- **データはあなたの iCloud と Mac にだけ。** アプリの運営者のサーバーはありません。レシートの写真も台帳も、運営者には届きません。
- **読み取りに使う AI は、あなたが契約しているもの。** 写真はその AI のサービスに送られます（あなたの契約の範囲で）。
- **台帳はふつうの CSV。** Numbers や Excel で開けます。確定申告の経費の整理にも使えます。

## 用意するもの

| | |
|---|---|
| iPhone | iOS 17 以上。アプリ「家計簿カメラ」 |
| Mac | iPhone と**同じ Apple ID**で、iCloud Drive をオンに |
| AI | 画像を読めて、Mac のファイルを扱えるもの。おすすめは [Claude Code](https://claude.com/claude-code)。Codex など AGENTS.md を読むものでも動きます |
| Python 3 | Mac に入っているもので動きます（追加の部品は要りません） |

Mac や AI が無い場合は、アプリの「この iPhone だけで読む」を選びます。iPhone の中（Vision の文字の読み取りと Apple Intelligence）で**日付・合計・店名・支払方法**を読みます。品目までは読みません。写真は iCloud に残るので、あとで Mac の AI を使い始めれば、品目まで読み直せます。

## 入れ方（Claude Code）

ターミナルで1行：

```bash
git clone https://github.com/hey-show123/kakeibo-camera.git ~/.claude/skills/kakeibo-camera
```

そのあと Claude Code に「家計簿カメラの準備をして」と言うと、家計簿のフォルダ（既定は `~/Documents/家計簿`）を作ります。
iPhone のアプリで1枚撮ってから「レシート読んで」と言えば、記帳が始まります。

更新するとき：

```bash
git -C ~/.claude/skills/kakeibo-camera pull
```

### Claude Desktop（チャット）で使うとき

このリポジトリを ZIP でダウンロードし、Claude の「設定」→「機能」→「スキル」からアップロードします。Mac のファイルを読み書きできるように、ファイル操作のコネクタ（Filesystem など）を有効にしてください。

### Codex など、ほかの AI

このリポジトリを好きな場所に置き、そのフォルダで AI を開いて「レシート読んで」と言います。AI は `AGENTS.md` → `SKILL.md` の手順に従います。

## 毎晩、自動で読ませる

### Claude Code のコマンドで（Mac の launchd）

```bash
~/.claude/skills/kakeibo-camera/scripts/schedule_nightly.sh          # 毎晩 21:00
~/.claude/skills/kakeibo-camera/scripts/schedule_nightly.sh 23 30    # 毎晩 23:30
~/.claude/skills/kakeibo-camera/scripts/schedule_nightly.sh --remove # やめる
```

Mac が寝ている時刻は、起きたときに1回だけ動きます。記録は `~/Documents/家計簿/logs/` に残ります。

### Claude デスクトップアプリの予定のタスクで

Claude デスクトップアプリで、予定のタスク（毎日決まった時刻に動く作業）を作り、次の文を入れます。

> 家計簿カメラの受信箱のレシートを読んで、台帳に入れて、アプリに数字を書き出して。kakeibo-camera の skill の手順どおりに。

## 使い方

| AI に言うこと | すること |
|---|---|
| レシート読んで | 受信箱の写真を読み、台帳に入れ、アプリに数字を出す |
| 家計を見直して | 使いすぎ・先月との違い・来月の予算の目安を書き、アプリの「見直し」タブに出す |
| 予算を月5万円にして | `budget.json` を直して、アプリに「あと使える額」を出す |
| 今月いくら使った？ | 台帳から答える |
| 先月の食費の内訳は？ | 台帳から答える |

## 家計簿のフォルダ

```
~/Documents/家計簿/
├── 台帳.csv          1行に1つの商品。値引き・消費税も別の行
├── budget.json       予算（アプリの「あと使える額」）
├── config.json       家族の共有フォルダなど、受信箱を足すとき
├── review.json       AI が書いた家計の見直し
└── receipts/         読み終えたレシートの写真（年/月ごと）
```

場所を変えたいときは、環境変数 `KAKEIBO_DIR` を設定します。

## 家族の iPhone からも送る

Apple ID が違う iPhone からは、iCloud Drive の共有フォルダを受信箱にします。手順は [SKILL.md の「家族の iPhone からも送るとき」](SKILL.md#家族の-iphone-からも送るとき)。

## うまくいかないとき

- **受信箱が見つからない**：iPhone のアプリで1枚撮り、Mac の Finder で iCloud Drive に「家計簿カメラ」フォルダができるのを待ちます。iPhone と Mac の Apple ID が同じか、両方で iCloud Drive がオンかを確かめてください。
- **アプリに数字が出ない**：AI が最後に `kakeibo export` まで行ったかを確かめます。アプリは開いたとき（と15秒ごと）に読み直します。
- **自動の予定で動かない**：`~/Documents/家計簿/logs/` の記録を見てください。Claude Code にログインしたままか、`claude` コマンドが動くかを確かめます。

## アプリについて

- [サポート](https://hey-show123.github.io/kakeibo-camera/)・[利用規約](https://hey-show123.github.io/kakeibo-camera/terms.html)・[プライバシーポリシー](https://hey-show123.github.io/kakeibo-camera/privacy.html)
- 不具合・ご要望は [Issues](https://github.com/hey-show123/kakeibo-camera/issues) へ。

## ライセンス

MIT
