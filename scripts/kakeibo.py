#!/usr/bin/env python3
"""家計簿カメラ（iPhone アプリ）の受信箱を読み、台帳を付けて、アプリに出す数字を書き出す補助スクリプト。

AI（Claude Code など）が SKILL.md の手順に従って使う。人が直接打ってもよい。

  python3 kakeibo.py init
      家計簿のフォルダ（既定 ~/Documents/家計簿）を作り、台帳・予算・設定のひな形を置く。
  python3 kakeibo.py where
      家計簿のフォルダと受信箱の場所、それぞれがあるかを表示する。
  python3 kakeibo.py list
      iCloud から最新の状態を取ってきてから、受信箱の未処理の写真を古い順に一覧する。
  python3 kakeibo.py archive <写真> <YYYY-MM-DD_店名_金額円.jpg>
      台帳に入れた写真を receipts/YYYY/MM/ へ移し、台帳の「証憑画像」列に入れるパスを表示する。
  python3 kakeibo.py set-aside <写真> 重複|対象外
      台帳に入れない写真を receipts/重複/ か receipts/対象外/ へ移す。
  python3 kakeibo.py next-id <YYYY-MM-DD>
      その日の次のレシートID（RCPT-YYYYMMDD-NNN）を表示する。
  python3 kakeibo.py export
      台帳と予算から kakeibo_summary.json を作り、受信箱へ書き出す（アプリの「お金の状況」に出る）。

家計簿のフォルダは、環境変数 KAKEIBO_DIR で変えられる。
受信箱の写真は消さず、必ず receipts/ の下へ移す。
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("KAKEIBO_DIR", Path.home() / "Documents" / "家計簿")).expanduser()
LEDGER = DATA_DIR / "台帳.csv"
BUDGET = DATA_DIR / "budget.json"
CONFIG = DATA_DIR / "config.json"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

MOBILE_DOCUMENTS = Path.home() / "Library" / "Mobile Documents"
# アプリの受信箱。iPhone と Mac が同じ Apple ID なら、ここに届く（Finder では iCloud Drive の「家計簿カメラ」）
APP_INBOX = Path(os.environ.get(
    "KAKEIBO_APP_INBOX", MOBILE_DOCUMENTS / "iCloud~com~shoheiyamazaki~KakeiboCamera" / "Documents")).expanduser()
APP_CONTAINER = "iCloud.com.shoheiyamazaki.KakeiboCamera"

LEDGER_HEADER = ["レシートID", "日付", "時刻", "店舗", "金額（総額）", "個別商品名", "数量", "金額（商品別）",
                 "大カテゴリー", "中カテゴリー", "支払方法", "経費判定", "勘定科目候補", "証憑画像"]
SUMMARY_NAME = "kakeibo_summary.json"
SYNC_MARKER = "_mac_sync.txt"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".heic", ".png"}
SET_ASIDE_DIRS = {"重複", "対象外"}
JST = timezone(timedelta(hours=9))


# ───────── 設定と受信箱 ─────────

def load_config() -> dict:
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return {}


def inboxes() -> list[tuple[str, Path, str]]:
    """(名前, フォルダ, brctl のコンテナID)。アプリの受信箱と、config.json の extra_inboxes（家族の共有フォルダなど）"""
    result = [("家計簿カメラ", APP_INBOX, APP_CONTAINER)]
    for item in load_config().get("extra_inboxes", []):
        path = Path(item).expanduser()
        if not path.is_absolute():
            # iCloud Drive の中のフォルダ名だけ書かれていたら、そこを探す
            path = MOBILE_DOCUMENTS / "com~apple~CloudDocs" / item
        result.append((path.name, path, "com.apple.CloudDocs"))
    return result


def require_data_dir() -> None:
    if not LEDGER.exists():
        sys.exit(f"家計簿のフォルダがまだありません: {DATA_DIR}\n先に `python3 {Path(__file__).name} init` を実行してください。")


# ───────── iCloud ─────────

def last_sync(container_id: str) -> str | None:
    result = subprocess.run(["brctl", "status", container_id], capture_output=True, text=True, check=False)
    m = re.search(r"last-sync:(\d{4}-\d{2}-\d{2} [\d:.]+)", re.sub(r"\x1b\[[0-9;]*m", "", result.stdout))
    return m.group(1) if m else None


def pull_from_icloud(inbox: Path, container_id: str, timeout: float = 60) -> None:
    """Mac は iCloud のフォルダの更新を自分から取りに行かないことがある。
    小さなファイルを置くと、上げる前にクラウドの最新状態を取りに行くので、それを利用して、終わったら消す。"""
    before = last_sync(container_id)
    marker = inbox / SYNC_MARKER
    try:
        marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S"))
    except OSError:
        return
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(2)
            if before is not None and last_sync(container_id) not in (None, before):
                time.sleep(2)
                return
        print(f"注意: {inbox.name} は{int(timeout)}秒待っても iCloud との同期を確認できませんでした。届いていない写真があるかもしれません。")
    finally:
        marker.unlink(missing_ok=True)


def materialize(path: Path) -> Path:
    """クラウドにしかない写真をダウンロードして、実体のパスを返す"""
    if path.name.startswith(".") and path.name.endswith(".icloud"):
        real = path.with_name(path.name[1:-len(".icloud")])
        subprocess.run(["brctl", "download", str(path)], check=False, capture_output=True)
        for _ in range(120):
            if real.exists():
                break
            time.sleep(0.5)
        path = real
    with path.open("rb") as f:  # 実体のないファイルは読むとダウンロードされる
        while f.read(1 << 20):
            pass
    return path


def inbox_images(inbox: Path) -> list[Path]:
    images = []
    for entry in inbox.iterdir():
        name = entry.name[1:-len(".icloud")] if entry.name.endswith(".icloud") else entry.name
        if Path(name).suffix.lower() in IMAGE_SUFFIXES and not name.startswith("."):
            images.append(entry)
    return sorted(images, key=lambda p: p.name.lstrip("."))


def unique_destination(dest: Path) -> Path:
    candidate, n = dest, 2
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem}_{n}{dest.suffix}")
        n += 1
    return candidate


def inbox_file(arg: str) -> Path:
    folders = [folder for _, folder, _ in inboxes()]
    path = Path(arg).expanduser()
    if not path.is_absolute():
        candidates = [folder / path for folder in folders if (folder / path).exists()]
        if len(candidates) != 1:
            sys.exit(f"受信箱に見つからないか、2つの受信箱に同じ名前があります。絶対パスで指定してください: {arg}")
        path = candidates[0]
    if not path.exists():
        sys.exit(f"見つかりません: {path}")
    if path.resolve().parent not in {f.resolve() for f in folders if f.exists()}:
        sys.exit(f"受信箱の写真ではありません: {path}")
    return path


# ───────── コマンド ─────────

def cmd_init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        with LEDGER.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(LEDGER_HEADER)
        print(f"作成: {LEDGER}")
    for name in ("budget.json", "config.json"):
        target = DATA_DIR / name
        if not target.exists():
            shutil.copy(TEMPLATES / name, target)
            print(f"作成: {target}")
    (DATA_DIR / "receipts").mkdir(exist_ok=True)
    print(f"家計簿のフォルダ: {DATA_DIR}")
    cmd_where()


def cmd_where() -> None:
    print(f"家計簿のフォルダ: {DATA_DIR}（{'あり' if DATA_DIR.exists() else 'まだ無い'}）")
    for name, folder, _ in inboxes():
        state = "あり" if folder.exists() else "まだ無い（iPhone のアプリで1枚撮ると、iCloud で作られます）"
        print(f"受信箱 [{name}]: {folder}（{state}）")


def cmd_list() -> None:
    require_data_dir()
    total = 0
    for name, folder, container_id in inboxes():
        if not folder.exists():
            print(f"[{name}] まだありません: {folder}")
            continue
        pull_from_icloud(folder, container_id)
        images = [materialize(p) for p in inbox_images(folder)]
        total += len(images)
        print(f"[{name}] {folder}")
        print(f"未処理: {len(images)}枚")
        for p in images:
            print(f"{p}\t{p.stat().st_size // 1024}KB")
    print(f"合計 未処理: {total}枚")


def cmd_archive(src_arg: str, name: str) -> None:
    require_data_dir()
    src = inbox_file(src_arg)
    m = re.match(r"(\d{4})-(\d{2})-\d{2}_", name)
    if not m:
        sys.exit("保存名は YYYY-MM-DD_店名_金額円.jpg の形にしてください（日付はレシートの取引日）")
    base = re.sub(r"\.[A-Za-z0-9]+$", "", name)  # 店名に「/」が入っていても切れないよう、拡張子だけ外す
    safe = re.sub(r'[\\/:*?"<>|]', "_", base)
    dest_dir = DATA_DIR / "receipts" / m.group(1) / m.group(2)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_destination(dest_dir / f"{safe}{src.suffix.lower()}")
    shutil.move(str(src), dest)
    print(dest.relative_to(DATA_DIR))


def cmd_set_aside(src_arg: str, reason: str) -> None:
    require_data_dir()
    if reason not in SET_ASIDE_DIRS:
        sys.exit("理由は 重複 か 対象外 を指定してください")
    src = inbox_file(src_arg)
    dest_dir = DATA_DIR / "receipts" / reason
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_destination(dest_dir / src.name)
    shutil.move(str(src), dest)
    print(dest.relative_to(DATA_DIR))


def cmd_next_id(date: str) -> None:
    require_data_dir()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        sys.exit("日付は YYYY-MM-DD で指定してください")
    prefix = f"RCPT-{date.replace('-', '')}-"
    used = [int(r["レシートID"][len(prefix):]) for r in read_ledger()
            if r["レシートID"].startswith(prefix) and r["レシートID"][len(prefix):].isdigit()]
    print(f"{prefix}{(max(used) if used else 0) + 1:03d}")


# ───────── アプリに出す数字（kakeibo_summary.json） ─────────

def read_ledger() -> list[dict]:
    with LEDGER.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def to_int(value) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def short_payment(text: str) -> str:
    if text.startswith("PayPay"):
        return "PayPay"
    if text.startswith("現金"):
        return "現金"
    if "デビット" in text:
        return "デビット"
    if any(k in text for k in ("Visa", "VISA", "Master", "JCB", "AMEX", "クレジット")):
        return "カード"
    if "電子マネー" in text or any(k in text for k in ("Suica", "PASMO", "iD", "QUICPay", "nanaco", "WAON", "楽天Edy")):
        return "電子マネー"
    return text or "不明"


def build_receipts(rows: list[dict]) -> list[dict]:
    receipts: OrderedDict[str, dict] = OrderedDict()
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        rid = r["レシートID"]
        item = receipts.setdefault(rid, {
            "id": rid, "date": r["日付"], "store": r["店舗"], "total": to_int(r["金額（総額）"]),
            "payment": r["支払方法"], "expense": False, "items": [],
        })
        if r["個別商品名"]:
            item["items"].append({"name": r["個別商品名"], "qty": to_int(r["数量"]) or 1,
                                  "amount": to_int(r["金額（商品別）"]), "category": r["大カテゴリー"]})
        if r.get("経費判定") == "経費":
            item["expense"] = True
        if r["大カテゴリー"] and r["大カテゴリー"] != "調整":
            by_category[rid][r["大カテゴリー"]] += to_int(r["金額（商品別）"])
    ordered = sorted(receipts.values(), key=lambda x: (x["date"], x["id"]), reverse=True)
    for item in ordered:
        item["payment"] = short_payment(item["payment"])
        cats = by_category.get(item["id"])
        if cats:
            item["category"] = max(cats.items(), key=lambda kv: kv[1])[0]
    return ordered


def build_categories(rows: list[dict], month: str) -> list[dict]:
    sums: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["日付"].startswith(month):
            name = "消費税・値引き" if r["大カテゴリー"] == "調整" else (r["大カテゴリー"] or "その他")
            sums[name] += to_int(r["金額（商品別）"])
    return [{"name": k, "amount": v} for k, v in sorted(sums.items(), key=lambda kv: -kv[1])]


def build_months(budget: dict, receipts: list[dict], current: str) -> list[dict]:
    """budget.json の月ごとの予算。spent が無い月は、台帳のその月の合計を使った額にする"""
    ledger_total: dict[str, int] = defaultdict(int)
    for r in receipts:
        ledger_total[r["date"][:7]] += r["total"]
    default_budget = budget.get("monthly_budget")
    explicit = {m["month"]: m for m in budget.get("months", [])}
    months = sorted(set(explicit) | ({current} if default_budget else set()))
    result = []
    for month in months:
        m = explicit.get(month, {})
        income = to_int(m.get("income", 0))
        if "budget" in m:
            allowance = to_int(m["budget"])
        elif income and budget.get("rate"):
            allowance = round(income * float(budget["rate"]))
        elif default_budget:
            allowance = to_int(default_budget)
        else:
            continue
        spent = to_int(m["spent"]) if "spent" in m else ledger_total.get(month, 0)
        result.append({"month": month, "income": income, "budget": allowance, "spent": spent, "balance": allowance - spent})
    return result


def cmd_export() -> None:
    require_data_dir()
    budget = json.loads(BUDGET.read_text(encoding="utf-8")) if BUDGET.exists() else {}
    rows = read_ledger()
    receipts = build_receipts(rows)
    current = datetime.now(JST).strftime("%Y-%m")
    months = build_months(budget, receipts, current)

    ledger = []
    for month in sorted({r["date"][:7] for r in receipts}):
        items = [r for r in receipts if r["date"].startswith(month)]
        ledger.append({"month": month, "total": sum(r["total"] for r in items), "receipts": items,
                       "categories": build_categories(rows, month)})

    summary = {
        "generatedAt": datetime.now(JST).isoformat(timespec="seconds"),
        "rule": budget.get("rule") or "数字は台帳に入れたレシートの合計です。",
        "note": budget.get("note"),
        "currentMonth": current,
        "months": months,
        "cumulative": sum(m["balance"] for m in months),
        "receipts": receipts[:40],
        "categoryMonth": current,
        "categories": build_categories(rows, current),
        "ledger": ledger,
    }
    text = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    written = 0
    for name, folder, _ in inboxes():
        if not folder.exists():
            print(f"スキップ（受信箱がまだ無い）: {folder}")
            continue
        tmp = folder / f".{SUMMARY_NAME}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, folder / SUMMARY_NAME)
        written += 1
        print(f"書き出し: {folder / SUMMARY_NAME}")
    month_total = sum(r["total"] for r in receipts if r["date"].startswith(current))
    print(f"{current} 台帳のレシート {len([r for r in receipts if r['date'].startswith(current)])}件 / 合計 {month_total:,}円")
    if months and months[-1]["month"] == current:
        m = months[-1]
        print(f"予算 {m['budget']:,}円 / 使った {m['spent']:,}円 / 残り {m['balance']:,}円")
    if written == 0:
        print("受信箱が1つも無いので、アプリには届いていません。iPhone のアプリで1枚撮ると受信箱ができます。")


def main() -> None:
    args = sys.argv[1:]
    commands = {
        ("init", 0): cmd_init, ("where", 0): cmd_where, ("list", 0): cmd_list, ("export", 0): cmd_export,
        ("archive", 2): cmd_archive, ("set-aside", 2): cmd_set_aside, ("next-id", 1): cmd_next_id,
    }
    command = commands.get((args[0], len(args) - 1)) if args else None
    if not command:
        sys.exit(__doc__)
    command(*args[1:])


if __name__ == "__main__":
    main()
