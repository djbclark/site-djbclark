#!/usr/bin/env python3
"""Site-specific hostname auditor for djbclark's macOS, Linux, and Android devices."""

from __future__ import annotations

import os
import subprocess
import sys

TARGET_MAC_NAME = "bigmac"
ANDROID_TARGETS = {
    "100.123.218.30:5555": "s24",
    "100.65.230.108:5555": "p7a",
    "100.124.55.39:5555": "hd8",
}
KNOWN_LINUX_HOSTS = {
    "100.72.30.90": "p7a-kvm",
    "vps-primary": "vps-primary",
}


def is_darwin() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def audit_mac_hostname() -> bool:
    if not is_darwin():
        return True

    print("=== macOS Hostname Audit ===")
    names = {}
    for key in ("ComputerName", "LocalHostName", "HostName"):
        try:
            result = subprocess.run(
                ["scutil", "--get", key],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            names[key] = result.stdout.strip() or "unknown"
        except (OSError, subprocess.TimeoutExpired):
            names[key] = "unknown"
        print(f"Current {key}: {names[key]}")

    if all(name == TARGET_MAC_NAME for name in names.values()):
        print(f"✓ macOS names match '{TARGET_MAC_NAME}'.")
        return True

    print(f"\n⚠️ WARNING: macOS names should match '{TARGET_MAC_NAME}'.")
    for key, name in names.items():
        if name != TARGET_MAC_NAME:
            print(f"  sudo scutil --set {key} '{TARGET_MAC_NAME}'")
    return False


def audit_local_linux_hostname(expected_name: str) -> bool:
    if is_linux():
        print("=== Linux Local Hostname Audit ===")
        try:
            r = subprocess.run(
                ["hostname"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            current_name = r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            current_name = "unknown"

        print(f"Current Linux Hostname: {current_name}")

        if current_name == expected_name:
            print(
                f"✓ Linux hostname is fully aligned with canonical name '{expected_name}'."
            )
            return True

        print(
            f"\n-> Reconciling local Linux hostname (current: '{current_name}') -> '{expected_name}'..."
        )
        try:
            r = subprocess.run(
                ["sudo", "-n", "hostnamectl", "set-hostname", expected_name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r.returncode == 0:
                print(f"✓ Successfully reconciled Linux hostname to '{expected_name}'.")
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass

        print(
            f"⚠️ WARNING: Linux hostname differs from canonical name '{expected_name}'!"
        )
        print(
            f"To align your Linux hostname, please run:\n  sudo hostnamectl set-hostname '{expected_name}'\n"
        )
        return False
    return True


def audit_remote_linux_hosts() -> None:
    print("=== Remote Linux Nodes Audit ===")
    for addr, expected_name in KNOWN_LINUX_HOSTS.items():
        try:
            r = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "ConnectTimeout=3",
                    "-o",
                    "BatchMode=yes",
                    f"djbclark@{addr}",
                    "hostname",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r.returncode == 0:
                current_name = r.stdout.strip()
                if current_name == expected_name:
                    print(
                        f"✓ Remote Linux node {addr} ({expected_name}) hostname is aligned."
                    )
                else:
                    print(
                        f"⚠️ Remote Linux node {addr} hostname is '{current_name}' (expected: '{expected_name}')!"
                    )
                    print(
                        f"  Run on {addr}: sudo hostnamectl set-hostname '{expected_name}'"
                    )
            else:
                print(
                    f"ℹ️ Remote Linux node {addr} ({expected_name}) unreachable or offline."
                )
        except (OSError, subprocess.TimeoutExpired):
            print(f"ℹ️ Remote Linux node {addr} ({expected_name}) offline.")


def reconcile_android_hostnames() -> None:
    print("=== Android Device Name Reconciliation ===")
    for addr, expected_name in ANDROID_TARGETS.items():
        try:
            r = subprocess.run(
                [
                    "adb",
                    "-s",
                    addr,
                    "shell",
                    "settings",
                    "get",
                    "global",
                    "device_name",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r.returncode != 0:
                print(
                    f"❌ Unable to read device name for {addr}: {r.stderr.strip() or 'adb failed'}"
                )
                continue
            current_name = r.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            current_name = "unreachable"

        if current_name == expected_name:
            print(f"✓ Android device at {addr} is set to '{expected_name}'.")
        else:
            print(
                f"-> Reconciling {addr} (current: '{current_name}') -> '{expected_name}'..."
            )
            try:
                result = subprocess.run(
                    [
                        "adb",
                        "-s",
                        addr,
                        "shell",
                        "settings",
                        "put",
                        "global",
                        "device_name",
                        expected_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    print(f"✓ Reconciled {addr} to '{expected_name}'.")
                else:
                    print(
                        f"❌ Failed to reconcile {addr}: {result.stderr.strip() or 'adb failed'}"
                    )
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"❌ Failed to reconcile {addr}: {e}")


def main() -> int:
    mac_ok = audit_mac_hostname()
    expected_linux_hostname = os.environ.get("STAYTURGID_EXPECTED_HOST", "").strip()
    if is_linux() and not expected_linux_hostname:
        print(
            "ℹ️ Linux hostname audit skipped; set STAYTURGID_EXPECTED_HOST to enable reconciliation."
        )
        linux_ok = True
    else:
        linux_ok = audit_local_linux_hostname(expected_linux_hostname)
    audit_remote_linux_hosts()
    reconcile_android_hostnames()
    return 0 if (mac_ok and linux_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
