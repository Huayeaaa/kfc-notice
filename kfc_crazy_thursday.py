"""肯德基疯狂星期四 · 每周清单抓取推送

本地运行（无推送，直接打印）：
    python kfc_crazy_thursday.py

配置 Server酱后推送到微信（支持多人，逗号分隔多个 SendKey）：
    set SCT_SENDKEYS=key1,key2,key3   (Windows cmd)
    python kfc_crazy_thursday.py

    单人仍可用旧变量：set SCT_SENDKEY=你的SendKey

自定义信息源（逗号分隔多个，按顺序回退）：
    set KFC_ARTICLE_URLS=https://sz.bendibao.com/xxx.shtm,https://cd.bendibao.com/yyy.shtm
"""

import os
import sys
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# 本地 Windows 控制台默认 GBK，无法打印 emoji，重配置为 UTF-8 避免崩溃
# （GitHub Actions 运行环境本就是 UTF-8，此操作无副作用）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 信息源列表：按顺序尝试，第一个"近 10 天内有更新"的源胜出。
# 说明：疯四菜单全国统一，城市页只是附加本地门店说明。
#   - 深圳本地宝页面已停更（2025-05-08），保留作为首选，一旦恢复更新即自动启用
#   - 成都本地宝页面持续更新，作为兜底的全国菜单源
# 可用环境变量 KFC_ARTICLE_URLS（逗号分隔）覆盖整个列表
_DEFAULT_URLS = [
    "https://sz.bendibao.com/youhui/2024111/953973.shtm",
    "https://cd.bendibao.com/youhui/202474/186068.shtm",
]
ARTICLE_URLS = [
    u.strip()
    for u in os.environ.get("KFC_ARTICLE_URLS", ",".join(_DEFAULT_URLS)).split(",")
    if u.strip()
]
# 多人推送：SCT_SENDKEYS 支持逗号分隔多个 SendKey；兼容旧变量 SCT_SENDKEY
SENDKEYS = [
    k.strip()
    for k in os.environ.get(
        "SCT_SENDKEYS", os.environ.get("SCT_SENDKEY", "")
    ).split(",")
    if k.strip()
]
FRESH_DAYS = 10   # 选源时：距今天超过该天数视为"源过期"，尝试下一个源
RECENT_DAYS = 2   # 推送前：更新日期必须在最近 N 天内，否则视为"本周尚未更新"，跳过等重试

# 状态去重：记录已推送过的"更新日期"，同一天多个 cron 时间点重试不会重复推送
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_push")
FORCE_PUSH = os.environ.get("FORCE_PUSH") == "1"     # 手动触发时强制重推（忽略状态）
FINAL_SLOT = os.environ.get("KFC_FINAL_SLOT") == "1"  # 当天最后一个重试时间点

CST = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}

# 目标站点均为国内站点，直连即可；禁用系统代理读取，
# 避免本机 VPN/代理开关导致请求失败（GitHub Actions 上无影响）
SESSION = requests.Session()
SESSION.trust_env = False


def fetch_page(url: str) -> str:
    r = SESSION.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def parse_deals(html: str) -> str:
    """提取正文纯文本。正文容器兜底链：article → .content → #zoom → body"""
    soup = BeautifulSoup(html, "html.parser")
    node = (
        soup.select_one("article")
        or soup.select_one(".content")
        or soup.select_one("#zoom")
        or soup.select_one(".article-content")
        or soup.body
    )
    return node.get_text("\n", strip=True)


def extract_update_date(text: str):
    """从正文找 '2026年7月30日' 这类日期，做新鲜度校验"""
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=CST)
    except ValueError:
        return None


def extract_menu(text: str) -> str:
    """从正文提炼纯菜单：编号菜品行 + '注' 行。

    只保留形如 '1、吮指原味鸡(4块)29.9元' 的行和 '注：...' 备注行，
    砍掉导语、公众号引流、页脚等噪音。提炼不到编号行时返回 None。
    """
    lines = [ln.strip() for ln in text.splitlines()]
    items = [ln for ln in lines if re.match(r"^\d+\s*[、.．]", ln)]
    if not items:
        return None
    # Server酱按 Markdown 渲染：普通单换行会被合并成一行，
    # 必须转成列表语法才能逐项分行；价格加粗便于快速扫读
    md_items = []
    for ln in items:
        item = re.sub(r"^\d+\s*[、.．]\s*", "", ln)          # 去掉原始编号
        item = re.sub(r"(\d+(?:\.\d+)?元)", r"**\1**", item)  # 价格加粗
        md_items.append(f"- {item}")
    menu = "\n".join(md_items)
    note = next((ln for ln in lines if ln.startswith("注")), None)
    if note:
        menu += f"\n> {note}"  # 备注用引用样式
    return menu


def push_one(sendkey: str, title: str, desp: str):
    """给单个 SendKey 推送。返回 (是否成功, 描述)"""
    try:
        r = SESSION.post(
            f"https://sctapi.ftqq.com/{sendkey}.send",
            data={"title": title[:32], "desp": desp},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            return False, f"接口报错: {data}"
        return True, "成功"
    except Exception as e:
        return False, str(e)


def push(title: str, desp: str):
    """向所有已配置的 SendKey 逐个推送；未配置时打印到控制台"""
    if not SENDKEYS:
        print("=" * 40)
        print(title)
        print("=" * 40)
        print(desp)
        return
    failed = 0
    for key in SENDKEYS:
        ok, msg = push_one(key, title, desp)
        # 日志中只显示 key 前 6 位，避免泄露完整 SendKey
        print(f"推送 {key[:6]}***：{'✅' if ok else '❌'} {msg}")
        if not ok:
            failed += 1
    if failed == len(SENDKEYS):
        # 所有人都失败才算整体失败，让 GitHub Actions 标红提醒你
        raise RuntimeError(f"全部 {failed} 个 SendKey 推送失败")
    if failed:
        print(f"⚠️ 有 {failed}/{len(SENDKEYS)} 个推送失败（其余成功）")


def pick_fresh_source(today):
    """按顺序尝试各信息源，返回 (url, text, date)；全部失效返回 (None, report, None)"""
    report = []
    for url in ARTICLE_URLS:
        try:
            text = parse_deals(fetch_page(url))
            d = extract_update_date(text)
        except Exception as e:
            report.append(f"- {url}：抓取失败（{e}）")
            continue
        if d and (today - d).days <= FRESH_DAYS:
            return url, text, d
        report.append(f"- {url}：最近更新 {d.date() if d else '未知'}")
    return None, "\n".join(report), None


def read_state() -> str:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def write_state(tag: str):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(tag)


def main():
    today = datetime.now(CST)
    url, text, update_date = pick_fresh_source(today)

    if url is None:
        # 所有源都过期或抓取失败 → 推告警而不是旧清单
        push(
            "⚠️ 疯四信息源全部失效",
            "所有候选源均已过期或无法访问，请更新 KFC_ARTICLE_URLS。\n\n" + text,
        )
        sys.exit(1)

    # 严校验：更新日期距今超过 RECENT_DAYS 天，说明还是上周的内容，本周尚未更新
    age = (today - update_date).days
    if age > RECENT_DAYS:
        print(f"源最近更新为 {update_date.date()}（{age} 天前），本周菜单尚未更新，本次跳过，等待重试")
        if FINAL_SLOT:
            # 当天最后一个时间点仍没更新 → 告知用户，避免"无声错过"
            push(
                "🍗 疯四菜单暂未更新",
                f"截至今天中午信息源仍未发布本周菜单（最后更新 {update_date.date()}）。"
                f"可稍后手动查看：{url}",
            )
        sys.exit(0)

    # 状态去重：同一期菜单已推过就跳过（多个 cron 时间点重试不会重复推送）
    tag = str(update_date.date())
    if not FORCE_PUSH and read_state() == tag:
        print(f"{tag} 期菜单已推送过，跳过")
        sys.exit(0)

    # 优先推送提炼后的纯菜单；提炼失败（源改版）时兜底推原文前 3500 字
    menu = extract_menu(text)
    if menu:
        body = f"更新于 {update_date.month}月{update_date.day}日\n\n{menu}"
    else:
        # 兜底推原文：单换行转成 Markdown 硬换行（两空格+换行），避免被合并
        body = (
            f"信息源：{url}（更新于 {update_date.month}月{update_date.day}日）\n\n"
            + text[:3500].replace("\n", "  \n")
        )
    push(f"🍗 肯德基疯狂星期四（{today.month}月{today.day}日）", body)
    write_state(tag)


if __name__ == "__main__":
    main()
