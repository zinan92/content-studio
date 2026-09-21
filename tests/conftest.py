"""Shared fixtures."""

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_vault_sources():
    """vault.INBOX_SOURCES / DAILY_SOURCES 是模块全局，profile.yaml 会重写它们。
    一个测试配过之后不复位，下一个没建 app 的测试读到的就是缩过的来源表，
    _allowed_folders() 的白名单跟着缩，读笔记直接被拒——test_writer 就是这么挂的。"""
    from content_studio import vault

    yield
    vault.configure(None)
