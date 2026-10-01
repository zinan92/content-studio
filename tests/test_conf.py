"""conf.py：Park 专属的东西摘成可选配置。最要紧的一条：不填 = Park 现在的值，一个字节都不变。"""
from datetime import date
import os
from pathlib import Path

import pytest

from content_studio import conf, consult

# 摘出来之前写死在代码里的值。改默认值 = 改 Park 正在用的行为，得先问他。
PARK_VALUES = {
    "standards": "~/.claude/skills/park-content-qa/SKILL.md",
    "consult.folder": "010_咨询",
    "consult.workdir": "~/.config/content-studio/consults",
    "paths.content_ops": "~/work/content-ops",
    "paths.content_downloader": "~/work/content-downloader",
    "paths.xingqiu": "~/work/wechat-xingqiu-shell",
    "paths.publish_toolkit": "~/content-toolkit/capabilities/publish",
    "paths.secrets": "~/.config/park/secrets.yaml",
    "paths.youtube_token": "~/.config/park/youtube-token.json",
    "skills.koubo": "~/.agents/skills/ask-park-video",
    "skills.gzh_design": "~/.claude/skills/gzh-design",
    "skills.shots": "~/.agents/skills/video-shotcraft/references/shots",
    "codex.model": "gpt-6.1-sol",
    "update.branch": "main",
    "update.remote": "origin",
    "service.label": "com.wendy.content-studio",
    "service.restart": "~/.local/bin/content-studio-restart",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for env, _ in conf.ENV_MAP.values():
        monkeypatch.delenv(env, raising=False)
    return monkeypatch


def test_nothing_configured_means_parks_current_values(clean_env) -> None:
    assert {k: default for k, (_, default) in conf.ENV_MAP.items()} == PARK_VALUES
    for key, old in PARK_VALUES.items():
        assert conf.value(key) == old
    assert conf.apply({}) == []
    assert conf.brand({}) == {"name": "帕克动手", "en": "PARK & CO.", "slogan": "企业家的 AI 产品经理",
                              "promise": "不交报告，交结果。", "logo": ""}


def test_module_constants_still_point_where_they_did() -> None:
    from content_studio import gzh_layout, platform_stats, publisher

    home = Path.home()
    assert publisher.PUBLISH_ROOT == home / "content-toolkit/capabilities/publish"
    assert publisher.XINGQIU == home / "work/wechat-xingqiu-shell"
    assert platform_stats.BILI_COOKIES == home / "content-toolkit/capabilities/publish/cookies/bilibili_creator.json"
    assert platform_stats.CONTENT_OPS == home / "work/content-ops"
    assert gzh_layout.SKILL_DIR == home / ".claude/skills/gzh-design"
    assert consult.FOLDER == "010_咨询"


def test_a_customer_profile_overrides_but_explicit_env_wins(clean_env) -> None:
    clean_env.setenv("CONTENT_OPS_PATH", "/explicit/ops")
    written = conf.apply({"standards": "~/客户/标准/SKILL.md", "paths": {"content_ops": "/客户/ops", "xingqiu": "  "},
                          "consult": {"folder": "咨询"}})
    assert set(written) == {"standards", "consult.folder"}
    assert conf.value("standards") == "~/客户/标准/SKILL.md"
    assert conf.value("consult.folder") == "咨询"
    assert conf.value("paths.content_ops") == "/explicit/ops"  # 已经显式设了的环境变量不动
    assert conf.value("paths.xingqiu") == PARK_VALUES["paths.xingqiu"]  # 空白 = 没填
    for env in ("CONTENT_STUDIO_QA_GUIDE", "CONTENT_STUDIO_CONSULT_FOLDER"):
        os.environ.pop(env, None)


def test_brand_goes_into_client_documents(tmp_path: Path) -> None:
    logo = tmp_path / "logo.svg"
    logo.write_text('<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>', encoding="utf-8")
    b = conf.brand({"brand": {"name": "小王工作室", "slogan": "做好内容", "logo": str(logo), "en": ""}})
    client = {"call": "阿皮", "title": "t", "body": "## 下一步\n- 发报告"}
    page = consult.render_client(client, day=date(2026, 9, 28), brand=b)
    assert "小王工作室" in page and "做好内容" in page and "帕克动手" not in page and "<circle" in page
    assert "不交报告，交结果。" in page  # 没填的项沿用默认
    default = consult.render_client(client, day=date(2026, 9, 28))
    assert "帕克动手" in default and "企业家的 AI 产品经理" in default and "PARK &amp; CO." in default
