"""对外简介：Park 对外只有一份 profile，正本是 Obsidian 里的 `000_park-os/park profile.md`。

9/30 Park：「我不用在各个平台不一样……增加一个个人简介 section，它是可编辑的，并且能链接到我的 Obsidian。
他就是我对外的一个 profile。」上午做的「每个平台各写一份」拿掉。

- 文件第一行是名字，后面的文字是简介；`![[图]]` 这类嵌入行原样留着，工作台不动它们。
- 工作台里改 → 写回这个文件；Obsidian 里改 → 工作台下次读就是新的。保存时带上读到时的修改时间：
  文件在这期间被 Obsidian 改过，就不覆盖，让他先刷新。
- 每个平台只记「哪天改成了哪一版」：和现在这一版一样 = 已同步；不一样 = 要更新。
- X 能直接改上去（x_profile.py，他点了才改）；别的平台没有改资料的接口，复制过去贴，贴完点一下。
- X 的名字最多 50、简介最多 160 字符：一份简介要到处用，就按最紧的这个写。
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote

FILE = "000_park-os/park profile.md"
X_NAME_MAX, X_BIO_MAX = 50, 160
# (key, 名字, 编辑页, 去哪改)
PLATFORMS: tuple[tuple[str, str, str | None, str], ...] = (
    ("douyin", "抖音", None, "抖音 App：我 → 编辑资料"),
    ("channels", "视频号", None, "微信：视频号 → 自己的主页 → 资料"),
    ("xiaohongshu", "小红书", None, "小红书 App：我 → 编辑资料"),
    ("x", "X", "https://x.com/settings/profile", "可以直接从这里改上去"),
    ("wechat_mp", "公众号", "https://mp.weixin.qq.com/", "后台 → 设置与开发 → 公众号设置 → 功能介绍（一年能改的次数有限）"),
    ("bilibili", "B 站", "https://account.bilibili.com/account/home", "个人中心 → 我的信息 → 我的签名"),
    ("youtube", "YouTube", "https://studio.youtube.com/", "YouTube Studio → 自定义 → 基本信息"),
)
PUSHABLE = ("x",)


class ProfileError(RuntimeError):
    """说给人听的一句话。"""


def _is_embed(line: str) -> bool:
    return line.strip().startswith("![")


def read(vault: Path) -> dict[str, Any]:
    path = vault / FILE
    if not path.is_file():
        return {"exists": False, "path": str(path), "name": "", "bio": "", "mtime": None, "obsidian": None, "embeds": 0}
    lines = path.read_text(encoding="utf-8").splitlines()
    text = [ln for ln in lines if not _is_embed(ln)]
    while text and not text[0].strip():
        text.pop(0)
    name = text[0].strip().lstrip("# ").strip() if text else ""
    bio = "\n".join(text[1:]).strip()
    return {"exists": True, "path": str(path), "name": name, "bio": bio, "mtime": path.stat().st_mtime,
            "obsidian": f"obsidian://open?path={quote(str(path))}", "embeds": sum(1 for ln in lines if _is_embed(ln))}


def write(vault: Path, *, name: str, bio: str, mtime: float | None) -> dict[str, Any]:
    name, bio = name.strip(), bio.strip()
    if not name:
        raise ProfileError("名字不能空")
    if len(name) > X_NAME_MAX:
        raise ProfileError(f"名字最多 {X_NAME_MAX} 个字（X 的上限），现在 {len(name)} 个")
    path = vault / FILE
    embeds: list[str] = []
    if path.is_file():
        if mtime is not None and abs(path.stat().st_mtime - mtime) > 1e-3:
            raise ProfileError("这份简介刚在 Obsidian 里改过，先刷新再改，免得把那边的改动盖掉")
        embeds = [ln for ln in path.read_text(encoding="utf-8").splitlines() if _is_embed(ln)]
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([name, "", bio, *([""] + embeds if embeds else [])]).rstrip("\n") + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".profile-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return read(vault)


def platforms(profile: dict[str, Any], applied: dict[str, Any], on: dict[str, bool], core: tuple[str, ...]) -> list[dict[str, Any]]:
    """每个开着的平台：synced 平台上就是这一版 / stale 改过但简介后来又变了 / never 还没改过。"""
    out = []
    for key, label, edit_url, where in PLATFORMS:
        if not on.get(key):
            continue
        rec = applied.get(key) or {}
        if not rec:
            state = "never"
        elif rec.get("name") == profile["name"] and rec.get("bio") == profile["bio"]:
            state = "synced"
        else:
            state = "stale"
        out.append({"key": key, "label": label, "edit_url": edit_url, "where": where, "core": key in core,
                    "can_push": key in PUSHABLE, "state": state, "applied_at": rec.get("at")})
    out.sort(key=lambda p: not p["core"])
    return out
