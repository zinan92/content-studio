"""Publish a finished video to a platform, only after Park confirms the exact payload.

Two steps: prepare (freeze video file, copy and mode) → confirm (run). The channels are
the content-ops scripts Park already uses; the workbench never logs in for him.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

CONTENT_OPS = Path(os.environ.get("CONTENT_OPS_PATH", "~/work/content-ops")).expanduser()
PUBLISH_ROOT = Path("~/content-toolkit/capabilities/publish").expanduser()
CONFIRM_WINDOW_SECONDS = 30 * 60
RUN_TIMEOUT_SECONDS = 45 * 60

XINGQIU = Path("~/work/wechat-xingqiu-shell").expanduser()


def _secret(section: str, key: str) -> str:
    try:
        import yaml

        data = yaml.safe_load(Path("~/.config/park/secrets.yaml").expanduser().read_text(encoding="utf-8")) or {}
        return str((data.get(section) or {}).get(key) or "")
    except Exception:  # noqa: BLE001 - 没配就是空，调用方会说缺什么
        return ""


def _gzh_html(article: str) -> str:
    if not article:
        return ""
    from . import gzh_layout

    page = gzh_layout.current(Path(article))
    return str(page) if page else ""


PUBLISHERS: dict[str, dict[str, Any]] = {
    "channels": {
        "label": "视频号",
        "needs": ("playwright",),
        "copy_key": "channels",
        "credential": PUBLISH_ROOT / "cookies/tencent_uploader/account.json",
        # 2026-09-21 Park：腾讯最近两个月开始封自动发布，以前能用。重新登录治不好平台侧的限制，
        # 所以这里不是「登录过期」——通道留着（万一他记错了或者以后解封），但按钮由 blocked 状态挡住。
        "blocked": "视频号最近开始限制自动发布，先手动上传",
        "login_hint": f"python3 {CONTENT_OPS}/scripts/push_wechat_channels_draft.py --login-only",
        "modes": {
            "draft": {"label": "存为视频号草稿", "argv": ["python3", str(CONTENT_OPS / "scripts/push_wechat_channels_draft.py"), "--headless", "--video", "{video}", "--title", "{title}", "--description", "{body}"]},
            "publish": {"label": "直接发表", "argv": ["python3", str(CONTENT_OPS / "scripts/push_wechat_channels_draft.py"), "--headless", "--publish", "--video", "{video}", "--title", "{title}", "--description", "{body}"]},
        },
    },
    "bilibili": {
        "label": "B 站",
        "needs": ("playwright",),
        "copy_key": "bilibili",
        "credential": PUBLISH_ROOT / "cookies/bilibili_creator.json",
        # 文件日期只能猜「大概过期了」，这条命令是真去问 B 站。2026-09-21 实测：cookie
        # 已经 4 个月没动，但依然 valid——只看 mtime 会把能用的通道报成要重新登录。
        "probe": [str(PUBLISH_ROOT / ".venv/bin/python"), str(PUBLISH_ROOT / "sau_cli.py"), "bilibili", "check", "--account", "creator"],
        "probe_ok": "valid",
        "login_hint": f"cd {PUBLISH_ROOT} && ./.venv/bin/python sau_cli.py bilibili login --account creator",
        "modes": {
            "upload": {"label": "投稿（B 站审核后公开）", "argv": ["python3", str(CONTENT_OPS / "scripts/bilibili_web_upload.py"), "--headless", "upload", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}", "--cover", "{cover}"]},
        },
    },
    "x": {
        "label": "X",
        "copy_key": "x",
        # 纯文字，没有视频：Park 说主要发文字，而发视频要走分块上传接口和付费层。
        # 凭据不是文件而是 secrets.yaml 里的一段，所以 credential 指向那个文件，
        # readiness 只看得见「文件在不在」——真正齐不齐由 x_post.load_credentials 说了算。
        "credential": Path("~/.config/park/secrets.yaml").expanduser(),
        "needs_keys": ("x", ("api_key", "api_secret", "access_token", "access_secret")),
        "login_hint": "在 developer.x.com 建应用（权限选 Read and Write），把四个密钥写进 ~/.config/park/secrets.yaml 的 x: 段",
        "no_video": True,
        # 9/23 Park：X 一定要是图文文章。发的是研习室文章 + 横版封面，不是文案框里那几行。
        "needs_article": True,
        "modes": {
            "article_draft": {"label": "存为 X 图文文章草稿", "argv": ["python3", "-m", "content_studio.x_article", "--article", "{article}", "--cover", "{cover}"]},
            "article_publish": {"label": "直接发布图文文章", "argv": ["python3", "-m", "content_studio.x_article", "--article", "{article}", "--cover", "{cover}", "--publish"]},
        },
    },
    "miniprogram": {
        "label": "研习室",
        "copy_key": "miniprogram",
        # 9/24 Park：研习室要一键发。云函数 admin-api 认「工作台钥匙」（zinan92/wechat-xingqiu#338），
        # 本机脚本用网页后台同一套转换；同一选题再发会更新同一篇（brief_id 固定）。
        "credential": Path("~/.config/park/secrets.yaml").expanduser(),
        "needs_keys": ("yanxishi", ("workbench_key", "env_id")),
        "secret_env": {"WORKBENCH_KEY": ("yanxishi", "workbench_key")},
        "login_hint": "研习室工作台钥匙在 ~/.config/park/secrets.yaml 的 yanxishi: 段（workbench_key、env_id），云函数 admin-api 存它的哈希",
        "no_video": True,
        "needs_article": True,
        "modes": {
            "draft": {"label": "存成研习室草稿", "argv": ["node", str(XINGQIU / "scripts/workbench-submit.mjs"), "--md", "{article}", "--html", "{gzh_html}", "--env", "{yanxishi_env}", "--brief-id", "{brief_id}"]},
            "publish": {"label": "直接发布到研习室", "argv": ["node", str(XINGQIU / "scripts/workbench-submit.mjs"), "--md", "{article}", "--html", "{gzh_html}", "--env", "{yanxishi_env}", "--brief-id", "{brief_id}", "--publish"]},
        },
    },
    "wechat_mp": {
        "label": "公众号",
        "copy_key": "wechat_mp",
        # 9/24 Park：公众号要一键发。研习室那篇文章排好版（橄榄手记）+ 公众号封面，进草稿箱；
        # 「发布」出现在公众号主页但不推送粉丝，推送（群发）不在这里做。
        "credential": Path("~/.config/park/secrets.yaml").expanduser(),
        "needs_keys": ("wechat", ("appid", "secret")),
        "login_hint": "公众号后台 → 设置与开发 → 基本配置：AppID、AppSecret 写进 ~/.config/park/secrets.yaml 的 wechat: 段，并把这台机器的 IP 加进白名单",
        "no_video": True,
        "needs_article": True,
        "modes": {
            "draft": {"label": "存进公众号草稿箱", "argv": ["python3", "-m", "content_studio.wechat_publish", "--article", "{article}", "--cover", "{cover}"]},
            "publish": {"label": "直接发布（不推送粉丝）", "argv": ["python3", "-m", "content_studio.wechat_publish", "--article", "{article}", "--cover", "{cover}", "--publish"]},
        },
    },
    "youtube": {
        "label": "YouTube",
        "copy_key": "youtube",
        "credential": Path("~/.config/park/youtube-token.json").expanduser(),
        "probe": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "check"],
        "probe_ok": "token_valid",
        "login_hint": f"python3 {CONTENT_OPS}/scripts/youtube_channel.py auth",
        "modes": {
            "private": {"label": "上传为私享（自己先看）", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload-private", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
            "public": {"label": "公开发布", "argv": ["python3", str(CONTENT_OPS / "scripts/youtube_channel.py"), "upload", "--privacy-status", "public", "--video", "{video}", "--title", "{title}", "--description", "{body}", "--tags", "{tags}"]},
        },
    },
}


class PublishError(ValueError):
    """Publishing cannot proceed; the message is shown to Park."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def readiness(publishers: dict[str, dict[str, Any]] = PUBLISHERS, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or now_utc()
    result = {}
    for key, spec in publishers.items():
        if spec.get("blocked"):
            # A platform-side block: the credential may be perfectly fine and re-scanning a QR
            # code fixes nothing. Saying 「要重新登录」 here would send Park off on a dead errand.
            result[key] = {"label": spec["label"], "credential": True, "age_days": None, "likely_expired": True,
                           "blocked": True, "note": spec["blocked"], "login_hint": "", "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")),
                           "modes": {m: v["label"] for m, v in spec["modes"].items()}}
            continue
        path = Path(spec["credential"])
        section = spec.get("needs_keys")
        if section and path.is_file():
            # A secrets file exists for other reasons (公众号 keys live there too), so its
            # presence proves nothing about X. Check the actual keys.
            try:
                import yaml

                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                have = (data.get(section[0]) or {}) if isinstance(data, dict) else {}
                missing = [k for k in section[1] if not str(have.get(k) or "").strip()]
            except Exception:  # noqa: BLE001 - unreadable means unconfigured
                missing = list(section[1])
            if missing:
                result[key] = {"label": spec["label"], "credential": False, "age_days": None, "likely_expired": True,
                               "setup": True, "note": f"还缺 {', '.join(missing)}", "login_hint": spec["login_hint"], "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")),
                               "modes": {m: v["label"] for m, v in spec["modes"].items()}}
                continue
        if path.is_file():
            updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            age = (now - updated).days
            stamp = updated.astimezone().strftime("%m-%d")
            # 有探测命令就以它为准：cookie 放了四个月照样可能有效，光看日期会误报。
            from .channel_probe import probe as probe_channel

            checked = probe_channel(key, spec)
            if checked is not None and checked.get("ok") is not None:
                expired = not checked["ok"]
                note = (f"登录信息更新于 {stamp}，刚才问过平台，能用" if checked["ok"]
                        else f"登录已失效（更新于 {stamp}），需要重新登录")
            else:
                expired = age > 30
                note = f"登录信息更新于 {stamp}" + ("，已超过 30 天，很可能需要重新登录" if expired else "")
            result[key] = {"label": spec["label"], "credential": True, "age_days": age, "likely_expired": expired, "note": note, "login_hint": spec["login_hint"],
                           "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")), "modes": {m: v["label"] for m, v in spec["modes"].items()}}
        else:
            result[key] = {"label": spec["label"], "credential": False, "age_days": None, "likely_expired": True, "note": "还没有登录信息", "login_hint": spec["login_hint"],
                           "no_video": bool(spec.get("no_video")), "needs_article": bool(spec.get("needs_article")), "modes": {m: v["label"] for m, v in spec["modes"].items()}}
    return result


def build_payload(platform: str, mode: str, *, video: Path | None, copy: dict[str, Any] | None, publishers: dict[str, dict[str, Any]] = PUBLISHERS,
                  article: Path | None = None, cover: Path | None = None) -> dict[str, Any]:
    spec = publishers.get(platform)
    if spec is None:
        raise PublishError("这个平台还不能一键发布")
    if mode not in spec["modes"]:
        raise PublishError("发布方式无效")
    if spec.get("needs_article"):
        if article is None or not article.is_file():
            raise PublishError("先在「研习室文章」写好文章，X 发的是图文文章")
        heading = next((l[2:].strip() for l in article.read_text(encoding="utf-8").splitlines() if l.startswith("# ")), "")
        return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
                "video": "", "video_mb": 0, "title": heading or article.stem, "body": "", "tags": [],
                "article": str(article), "cover": str(cover) if cover and cover.is_file() else ""}
    text_only = bool(spec.get("no_video"))
    if not text_only and (video is None or not video.is_file()):
        raise PublishError("找不到成片文件")
    entry = (copy or {}).get(spec["copy_key"]) or {}
    title = str(entry.get("title") or "").strip()
    body = str(entry.get("body") or "").strip()
    tags = [str(t).strip() for t in entry.get("tags") or [] if str(t).strip()]
    if text_only:
        # X 发的是正文本身，没有标题这一栏——要求填标题会把他卡在一个根本不存在的字段上。
        if not body:
            raise PublishError(f"先在「发布」页写好{spec['label']}的正文并保存")
        return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
                "video": "", "video_mb": 0, "title": title or body[:20], "body": body, "tags": tags}
    if not title:
        raise PublishError(f"先在「发布」页写好标题并保存")
    return {"platform": platform, "platform_label": spec["label"], "mode": mode, "mode_label": spec["modes"][mode]["label"],
            "video": str(video), "video_mb": round(video.stat().st_size / 1_048_576, 1), "title": title, "body": body, "tags": tags,
            "cover": str(cover) if cover and cover.is_file() else ""}


# 9/24 B 站投稿报 No module named 'playwright'：工作台后台 PATH 里第一个 python3 是 Homebrew 的，
# 没装 playwright。命令里写的「python3」不再交给 PATH 去猜，按这个通道要的库挑解释器。
PYTHON_CANDIDATES = (sys.executable, "/usr/local/bin/python3", "/usr/bin/python3", "/opt/homebrew/bin/python3")
_PYTHON_FOR: dict[tuple[str, ...], str] = {}


def python_with(modules: tuple[str, ...], candidates: tuple[str, ...] = PYTHON_CANDIDATES) -> str:
    if not modules:
        return sys.executable
    if modules in _PYTHON_FOR:
        return _PYTHON_FOR[modules]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            done = subprocess.run([candidate, "-c", "import " + ", ".join(modules)], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if done.returncode == 0:
            _PYTHON_FOR[modules] = candidate
            return candidate
    raise PublishError(f"这台机器上找不到装了 {'、'.join(modules)} 的 Python：在终端运行 /usr/local/bin/python3 -m pip install {' '.join(modules)}")


def command_for(payload: dict[str, Any], publishers: dict[str, dict[str, Any]] = PUBLISHERS) -> list[str]:
    spec = publishers[payload["platform"]]
    template = list(spec["modes"][payload["mode"]]["argv"])
    if template and template[0] == "python3":
        template[0] = python_with(tuple(spec.get("needs") or ()))
    article = payload.get("article", "")
    values = {"video": payload["video"], "title": payload["title"], "body": payload["body"], "tags": ",".join(payload["tags"]),
              "article": article, "cover": payload.get("cover", ""),
              # 同一选题的文章放在 drafts/topic-<id>/ 下：拿目录名当稳定 id，再发会更新同一篇而不是新建
              "brief_id": f"content-studio-{Path(article).parent.name}" if article else "",
              "yanxishi_env": _secret("yanxishi", "env_id") if "{yanxishi_env}" in template else "",
              # gzh skill 排好的版（和文章对得上才用）；没有就空着，脚本按 Markdown 导入
              "gzh_html": _gzh_html(article) if "{gzh_html}" in template else ""}
    # Only whole-argument placeholders are substituted, so titles with braces never break the command.
    return [values[part[1:-1]] if part[1:-1] in values and part.startswith("{") and part.endswith("}") else part for part in template]


def confirmable(job: dict[str, Any], now: datetime | None = None) -> None:
    if job["state"] != "awaiting_confirm":
        raise PublishError("这个发布任务不在等待确认")
    created = datetime.fromisoformat(job["created_at"].replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if ((now or now_utc()) - created).total_seconds() > CONFIRM_WINDOW_SECONDS:
        raise PublishError("确认已超过 30 分钟，请重新准备发布")


def parse_result(stdout: str) -> dict[str, Any]:
    """The scripts print one JSON object; take the last parseable one."""
    for match in reversed(list(re.finditer(r"\{", stdout))):
        try:
            value = json.loads(stdout[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def run(payload: dict[str, Any], *, publishers: dict[str, dict[str, Any]] = PUBLISHERS, timeout: float = RUN_TIMEOUT_SECONDS) -> dict[str, Any]:
    argv = command_for(payload, publishers)
    env = None
    wanted = publishers[payload["platform"]].get("secret_env") or {}
    if wanted:
        # 钥匙走环境变量，不进命令行参数（ps 里看得见）
        env = {**os.environ, **{name: _secret(*where) for name, where in wanted.items()}}
    try:
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env,
                                   cwd=str(CONTENT_OPS) if CONTENT_OPS.is_dir() else None)
    except subprocess.TimeoutExpired:
        return {"ok": False, "status": "timeout", "message": "发布超时（45 分钟），去平台后台看看有没有上传成功"}
    except OSError as exc:
        return {"ok": False, "status": "command_missing", "message": f"找不到发布脚本：{exc}"}
    result = parse_result(completed.stdout)
    if not result:
        result = {"ok": False, "status": "no_result", "message": (completed.stderr or completed.stdout).strip()[-400:]}
    result.setdefault("ok", completed.returncode == 0)
    return result


def result_url(result: dict[str, Any]) -> str | None:
    for key in ("url", "video_url", "link", "watch_url"):
        if str(result.get(key) or "").startswith("http"):
            return result[key]
    if result.get("video_id") and str(result.get("platform") or "youtube") == "youtube":
        return f"https://www.youtube.com/watch?v={result['video_id']}"
    return None


STATUS_TEXT = {
    "cookie_missing": "还没有登录信息，需要先在电脑上登录",
    "cookie_invalid": "登录已过期，需要在电脑上重新扫码登录",
    "video_missing": "找不到视频文件",
}


def explain(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "")
    return STATUS_TEXT.get(status) or str(result.get("message") or status or "发布失败")[:300]
