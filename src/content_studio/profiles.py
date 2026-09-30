"""各平台主页：别人点进来第一眼看到的名字、简介、链接，在工作台里写、存，再贴到平台上。

9/30 Park：「我想要慢慢把更多的东西放到这个内容工作台，比如各个 social media 的 profile，要能够在这个地方编辑。
现在我的 X profile 太简单了，根本就没有告诉别人我是做什么的。」

- 工作台是这几段文字的正本：名字、简介、链接。它们都从「定位」来，所以放在定位页最下面。
- X 能直接改（x_profile.py，老的 v1.1 账号接口）：卡片上「改到 X 上」，他点了才改。
  其余平台没有改资料的接口：每张卡给「复制」「打开平台的编辑页」，他贴完点「已经改到平台上了」。
- 只写有把握的字数上限（X：名字 50、简介 160、位置 30）。别的平台不写死，只显示现在多少字。
"""
from __future__ import annotations

from typing import Any

# (key, 名字, 编辑页, 上限 {字段: 字数}, 一句提示)
SPECS: tuple[tuple[str, str, str | None, dict[str, int], str], ...] = (
    ("douyin", "抖音", None, {}, "在抖音 App 里改：我 → 编辑资料"),
    ("channels", "视频号", None, {}, "在微信里改：视频号 → 自己的主页 → 资料"),
    ("xiaohongshu", "小红书", None, {}, "在小红书 App 里改：我 → 编辑资料"),
    ("x", "X", "https://x.com/settings/profile", {"name": 50, "bio": 160}, "名字最多 50 字符，简介最多 160 字符。可以直接从这里改到 X 上"),
    ("wechat_mp", "公众号", "https://mp.weixin.qq.com/", {}, "公众号后台 → 设置与开发 → 公众号设置 → 功能介绍（一年能改的次数有限）"),
    ("bilibili", "B 站", "https://account.bilibili.com/account/home", {}, "个人中心 → 我的信息 → 我的签名"),
    ("youtube", "YouTube", "https://studio.youtube.com/", {}, "YouTube Studio → 自定义 → 基本信息"),
)
FIELDS = ("name", "bio", "link")
PUSHABLE = ("x",)  # 能从工作台直接改到平台上的


def view(saved: dict[str, Any], on: dict[str, bool], core: tuple[str, ...]) -> list[dict[str, Any]]:
    """每个开着的平台一张卡。state：empty 没写 / draft 写了还没改到平台 / applied 平台上就是这一版。"""
    out = []
    for key, label, edit_url, limits, hint in SPECS:
        if not on.get(key, False):
            continue
        rec = saved.get(key) or {}
        now = {f: str(rec.get(f) or "") for f in FIELDS}
        applied = rec.get("applied") or {}
        if not any(now.values()):
            state = "empty"
        elif applied and all(str(applied.get(f) or "") == now[f] for f in FIELDS):
            state = "applied"
        else:
            state = "draft"
        out.append({"key": key, "label": label, "edit_url": edit_url, "limits": limits, "hint": hint, "core": key in core, "can_push": key in PUSHABLE,
                    **now, "state": state, "applied_at": applied.get("at")})
    out.sort(key=lambda p: not p["core"])
    return out


def check(key: str, fields: dict[str, str]) -> dict[str, str]:
    spec = next((s for s in SPECS if s[0] == key), None)
    if spec is None:
        raise ValueError("没有这个平台")
    clean = {f: (fields.get(f) or "").strip() for f in FIELDS}
    for f, cap in spec[3].items():
        if len(clean[f]) > cap:
            raise ValueError(f"{spec[1]}的{'名字' if f == 'name' else '简介'}最多 {cap} 个字，现在 {len(clean[f])} 个")
    return clean
