"""Pytest-Playwright shared fixtures for local and remote (Basic Auth) E2E runs."""

import os
import pytest


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    user = os.environ.get("E2E_HTTP_USER", "").strip()
    password = os.environ.get("E2E_HTTP_PASS", "").strip()
    if user and password:
        return {
            **browser_context_args,
            "http_credentials": {"username": user, "password": password},
        }
    return browser_context_args
