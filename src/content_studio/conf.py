"""可选配置：把「只在 Park 这台电脑上成立」的东西摘成 profile.yaml 里的项。

Park 9/28：工作台要装到客户（博主）的 Mac 上，但「不要动我现在在用的」。所以这里的规矩是：

- **不填 = Park 现在的值。** 每一项的默认值就是原来写死在代码里的那个值，
  Park 的 profile.yaml 里没有这些项，他这台电脑的行为一个字节都不变。
- 给客户装机时，Park 在客户那份 profile.yaml 里填客户自己的值。
- 落地方式沿用已有的做法：profile 里填了的项在启动时写成环境变量（环境变量已经设了的不动，
  那是显式覆盖），各模块读环境变量，读不到用默认值。
- `apply()` 在包导入时就跑（见 __init__.py），这样各模块在导入时算出的常量也能拿到。

对照表（给人看的版本）在 Park 的 vault：009_product-os/内容工作台/配置单.md。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SKIP_ENV = "CONTENT_STUDIO_SKIP_PROFILE_ENV"  # 测试里设上，别让本机 profile.yaml 漏进测试

# profile.yaml 里的点分路径 → 环境变量 → 不填时的默认值（= Park 现在的值）
ENV_MAP: dict[str, tuple[str, str]] = {
    "standards": ("CONTENT_STUDIO_QA_GUIDE", "~/.claude/skills/park-content-qa/SKILL.md"),
    "consult.folder": ("CONTENT_STUDIO_CONSULT_FOLDER", "010_咨询"),
    "consult.workdir": ("CONTENT_STUDIO_CONSULTS", "~/.config/content-studio/consults"),
    "paths.content_ops": ("CONTENT_OPS_PATH", "~/work/content-ops"),
    "paths.content_downloader": ("CONTENT_DOWNLOADER_PATH", "~/work/content-downloader"),
    "paths.xingqiu": ("CONTENT_STUDIO_XINGQIU", "~/work/wechat-xingqiu-shell"),
    "paths.publish_toolkit": ("CONTENT_STUDIO_PUBLISH_TOOLKIT", "~/content-toolkit/capabilities/publish"),
    "paths.secrets": ("PARK_SECRETS", "~/.config/park/secrets.yaml"),
    "paths.youtube_token": ("CONTENT_STUDIO_YOUTUBE_TOKEN", "~/.config/park/youtube-token.json"),
    # 形象照：出封面时「好看版的他」（10/1 Park：视频那一帧是普通版，和这几张合起来出封面上的人）
    "paths.portraits": ("CONTENT_STUDIO_PORTRAITS", "~/park-hands/000_park-os/形象照"),
    "skills.koubo": ("CONTENT_STUDIO_KOUBO_SKILL", "~/.agents/skills/ask-park-video"),
    "skills.gzh_design": ("CONTENT_STUDIO_GZH_SKILL", "~/.claude/skills/gzh-design"),
    "skills.shots": ("CONTENT_STUDIO_SHOTS", "~/.agents/skills/video-shotcraft/references/shots"),
    # 出封面、配插图用的 Codex 模型（10/1 Park：固定用 gpt-6.1-sol；不跟着本机 ~/.codex/config.toml 的默认值变）
    "codex.model": ("CONTENT_STUDIO_CODEX_MODEL", "gpt-6.1-sol"),
    # 「检查更新」拉哪个分支；客户装机时填 stable（Park 挑好的版本），Park 自己是 main
    "update.branch": ("CONTENT_STUDIO_UPDATE_BRANCH", "main"),
    "update.remote": ("CONTENT_STUDIO_UPDATE_REMOTE", "origin"),
    # 后台服务：launchd 的名字和安全重启脚本
    "service.label": ("CONTENT_STUDIO_SERVICE_LABEL", "com.wendy.content-studio"),
    "service.restart": ("CONTENT_STUDIO_RESTART", "~/.local/bin/content-studio-restart"),
}

# 品牌：工作台左上角、给客户的纪要和报告。不填 = 帕克动手。
BRAND_DEFAULT: dict[str, str] = {
    "name": "帕克动手",
    "en": "PARK & CO.",
    "slogan": "企业家的 AI 产品经理",
    "promise": "不交报告，交结果。",
    "logo": "",  # 一个 SVG 文件的路径；不填用对勾
}


def _get(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _load() -> dict[str, Any]:
    from . import profile

    try:
        return profile.load()
    except Exception:  # noqa: BLE001 - profile 写坏了不该让工作台起不来；`content-studio check` 会报出来
        return {}


def apply(data: dict[str, Any] | None = None) -> list[str]:
    """profile 里填了的项写成环境变量。返回这次写了哪些（给 check / 日志用）。"""
    if data is None and os.environ.get(SKIP_ENV):
        return []
    data = _load() if data is None else data
    written = []
    for key, (env, _default) in ENV_MAP.items():
        value = _get(data, key)
        if value is None or not str(value).strip() or os.environ.get(env):
            continue
        os.environ[env] = str(value).strip()
        written.append(key)
    return written


def value(key: str) -> str:
    """这一项现在生效的值：环境变量 → 默认值。"""
    env, default = ENV_MAP[key]
    return os.environ.get(env) or default


def path(key: str) -> Path:
    return Path(value(key)).expanduser()


def brand(data: dict[str, Any] | None = None) -> dict[str, str]:
    if data is None:
        data = {} if os.environ.get(SKIP_ENV) else _load()
    cfg = data.get("brand") if isinstance(data.get("brand"), dict) else {}
    return {k: str(cfg.get(k) or "").strip() or v for k, v in BRAND_DEFAULT.items()}
