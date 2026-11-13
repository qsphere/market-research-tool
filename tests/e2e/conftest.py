"""E2E fixtures: the real app process + a fake Nominatim/Overpass server, driven by Playwright."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.e2e.fake_services import FakeServices

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake():
    services = FakeServices()
    services.start()
    yield services
    services.stop()


@pytest.fixture
def app_url(tmp_path, fake):
    port = free_port()
    env = {
        **os.environ,
        "LEADGEN_PORT": str(port),
        "LEADGEN_DB_PATH": str(tmp_path / "e2e.db"),
        "LEADGEN_NOMINATIM_URL": fake.url,
        "LEADGEN_OVERPASS_URL": fake.url + "/interpreter",
        "LEADGEN_MAX_ATTEMPTS": "1",  # fail fast instead of backing off in the failure journey
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "leadgen"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"app exited early: {proc.stderr.read().decode()}")
        try:
            if httpx.get(url + "/", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("app did not start")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
