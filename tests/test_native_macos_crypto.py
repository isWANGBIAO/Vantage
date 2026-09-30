"""Prevent frozen Intel macOS runtimes mixing incompatible OpenSSL dylibs."""

from types import SimpleNamespace

import pytest

from src.scripts import sync_backend_runtime_environment as sync


def test_intel_mac_builds_current_crypto_statically_without_cached_dynamic_wheels():
    inherited = {"PATH": "/toolchain", "OPENSSL_STATIC": "0"}
    flags, env = sync.backend_install_policy(
        {"sys_platform": "darwin", "machine": "x86_64"}, inherited,
    )
    assert flags == ["--no-binary=cryptography", "--no-cache-dir"]
    assert env == {"PATH": "/toolchain", "OPENSSL_STATIC": "1"}
    assert inherited["OPENSSL_STATIC"] == "0"
    assert not any("cryptography==" in flag for flag in flags)


def test_arm_mac_keeps_official_wheel_while_non_mac_installs_stay_unchanged():
    flags, env = sync.backend_install_policy(
        {"sys_platform": "darwin", "machine": "arm64"}, {},
    )
    assert flags == []
    assert env == {"OPENSSL_STATIC": "1"}
    for platform in ("linux", "win32"):
        assert sync.backend_install_policy({"sys_platform": platform}, {}) == ([], None)


@pytest.mark.parametrize("link", [
    "/usr/local/opt/openssl@3/lib/libssl.3.dylib",
    "@rpath/libcrypto.3.dylib",
    "libssl.3.dylib",
])
def test_macos_import_probe_rejects_each_dynamic_crypto_dependency(monkeypatch, link):
    monkeypatch.setattr(sync.sys, "platform", "darwin")
    monkeypatch.setattr("importlib.import_module", lambda _: SimpleNamespace(__file__="/fixture/_rust.abi3.so"))
    monkeypatch.setattr(sync.subprocess, "run", lambda *_, **__: SimpleNamespace(stdout=f"/fixture/_rust.abi3.so:\n\t{link} (compatibility version 3.0.0)\n"))
    with pytest.raises(RuntimeError, match="statically link OpenSSL"):
        exec(sync._REQUIRED_IMPORTS_PROBE, {})


def test_macos_static_probe_checks_linkage_and_imports_ssl_crypto_mcp(monkeypatch):
    imported, commands = [], []
    monkeypatch.setattr(sync.sys, "platform", "darwin")

    def load(name):
        imported.append(name)
        return SimpleNamespace(__file__="/fixture/_rust.abi3.so")

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(stdout="/fixture/_rust.abi3.so:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n")

    monkeypatch.setattr("importlib.import_module", load)
    monkeypatch.setattr(sync.subprocess, "run", run)
    exec(sync._REQUIRED_IMPORTS_PROBE, {})
    assert {"ssl", "cryptography.hazmat.bindings._rust", "mcp"} <= set(imported)
    assert commands == [(["/usr/bin/otool", "-L", "/fixture/_rust.abi3.so"], {
        "check": True, "capture_output": True, "text": True, "timeout": 15,
    })]
