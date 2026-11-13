"""roles/tart_route fix-vmnet-route.sh: table test with fixture inputs, dry-run sudo.

No privileges: FIX_VMNET_ROUTE_FIXTURE_DIR supplies the netstat and ifconfig text,
FIX_VMNET_ROUTE_DRYRUN=1 prints the sudo argv instead of running it.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "roles/tart_route/files/fix-vmnet-route.sh"

D64 = "sudo -n /sbin/route -n delete -net 192.168.64.0/24 192.168.68.1"
A64 = "sudo -n /sbin/route -n add -net 192.168.64.0/24 -interface bridge100"
D65 = "sudo -n /sbin/route -n delete -net 192.168.65.0/24 192.168.68.1"


def add65(b: str) -> str:
    return f"sudo -n /sbin/route -n add -net 192.168.65.0/24 -interface {b}"


def ifc(**holders: str) -> str:
    return "lo0: flags=8049<UP> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n" + "".join(
        f"{b}: flags=8863<UP> mtu 1500\n\tinet {ip} netmask 0xffffff00 broadcast x\n"
        for b, ip in holders.items()
    )


def ns(*routes: tuple[str, str, str, str]) -> str:
    head = "Routing tables\n\nInternet:\nDestination        Gateway            Flags               Netif Expire\n"
    base = "default            192.168.68.1       UGScg                 en0\n"
    return head + base + "".join(f"{d:<18} {g:<18} {f:<19} {n}\n" for d, g, f, n in routes)


OK65 = ns(("192.168.65", "link#20", "UC", "bridge100"))
BAD65 = ns(("192.168.65", "192.168.68.1", "UGSc", "en0"))
OK64 = ns(("192.168.64", "link#20", "UC", "bridge100"))
BAD64 = ns(("192.168.64", "192.168.68.1", "UGSc", "en0"))
OK64_ON_100 = ("192.168.64", "link#20", "UC", "bridge100")

# name, ifconfig, netstat, expected rc, expected DRYRUN argv lines, output fragment
CASES = [
    ("ok65", ifc(bridge100="192.168.65.1"), OK65, 0, [], "already on bridge100"),
    ("bad65_b100", ifc(bridge100="192.168.65.1"), BAD65, 0, [D65, add65("bridge100")], "restored"),
    (
        "bad65_b101",
        ifc(bridge100="192.168.64.1", bridge101="192.168.65.1"),
        ns(("192.168.65", "192.168.68.1", "UGSc", "en0"), OK64_ON_100),
        0,
        [D65, add65("bridge101")],
        "restored",
    ),
    ("ok64", ifc(bridge100="192.168.64.1"), OK64, 0, [], "already on bridge100"),
    ("bad64_b100", ifc(bridge100="192.168.64.1"), BAD64, 0, [D64, A64], "restored"),
    ("absent64_b100", ifc(bridge100="192.168.64.1"), ns(), 0, [A64], "restored"),
    ("bad64_b101", ifc(bridge101="192.168.64.1"), BAD64, 1, [], "hand fix"),
    (
        "ok64_b101",
        ifc(bridge101="192.168.64.1"),
        ns(("192.168.64", "link#21", "UC", "bridge101")),
        0,
        [],
        "already on bridge101",
    ),
    (
        "other_gw64",
        ifc(bridge100="192.168.64.1"),
        ns(("192.168.64", "192.168.1.1", "UGSc", "en0")),
        1,
        [],
        "not 192.168.68.1",
    ),
    ("no_bridge", ifc(), ns(), 0, [], "no bridge holds"),
    (
        "wide64",
        ifc(bridge100="192.168.64.1"),
        ns(("192.168.64/23", "192.168.68.1", "UGSc", "en0")),
        1,
        [],
        "covers",
    ),
    (
        "wide65",
        ifc(bridge100="192.168.65.1"),
        ns(("192.168.64/23", "192.168.68.1", "UGSc", "en0")),
        1,
        [],
        "covers",
    ),
]


def run(
    ifconfig: str, netstat: str, *args: str, dry: bool = True, fail: bool = False, after: str | None = None
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "ifconfig").write_text(ifconfig)
        pathlib.Path(d, "netstat").write_text(netstat)
        if fail:
            pathlib.Path(d, "fail").write_text("")
        if after is not None:
            pathlib.Path(d, "netstat_after").write_text(after)
        env = {"PATH": "/usr/bin:/bin", "FIX_VMNET_ROUTE_FIXTURE_DIR": d}
        if dry:
            env["FIX_VMNET_ROUTE_DRYRUN"] = "1"
        return subprocess.run(
            ["/bin/sh", str(SCRIPT), *args], check=False, env=env, capture_output=True, text=True
        )


@pytest.mark.parametrize("name,ifconfig,netstat,rc,dry,frag", CASES, ids=[c[0] for c in CASES])
def test_cases(name, ifconfig, netstat, rc, dry, frag):
    r = run(ifconfig, netstat)
    assert r.returncode == rc, (r.stdout, r.stderr)
    assert [x for x in r.stdout.splitlines() if x.startswith("DRYRUN")] == ["DRYRUN " + x for x in dry]
    assert frag in r.stdout + r.stderr


def test_quiet_prints_nothing_when_ok():
    r = run(ifc(bridge100="192.168.64.1"), OK64, "-q")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_dryrun_is_not_a_way_to_run_something_else():
    assert "DRYRUN" not in SCRIPT.read_text().replace("FIX_VMNET_ROUTE_DRYRUN", "").replace(
        'echo "DRYRUN sudo', ""
    )
    assert os.access(SCRIPT, os.X_OK)


BOTH = ifc(bridge100="192.168.64.1", bridge101="192.168.65.1")
BAD_BOTH = ns(("192.168.65", "192.168.68.1", "UGSc", "en0"), ("192.168.64", "192.168.68.1", "UGSc", "en0"))


def drylines(r):
    return [x for x in r.stdout.splitlines() if x.startswith("DRYRUN")]


def test_both_subnets_bad_at_once():
    r = run(BOTH, BAD_BOTH)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert drylines(r) == ["DRYRUN " + x for x in (D65, add65("bridge101"), D64, A64)]


def test_failed_delete_other_writer_fixed_it():
    r = run(ifc(bridge100="192.168.64.1"), BAD64, fail=True, after=OK64)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert drylines(r) == ["DRYRUN " + D64]
    assert "another writer" in r.stdout


def test_failed_delete_still_bad_exits_3_but_other_subnet_is_fixed():
    r = run(BOTH, BAD_BOTH, fail=True)
    assert r.returncode == 3, (r.stdout, r.stderr)
    assert drylines(r) == ["DRYRUN " + D65, "DRYRUN " + D64]
    assert "sudoers.d/tart-route" in r.stderr and "sudoers.d/container-route" in r.stderr


def test_fixture_dir_implies_dryrun():
    with tempfile.TemporaryDirectory() as d:
        pathlib.Path(d, "ifconfig").write_text(ifc(bridge100="192.168.64.1"))
        pathlib.Path(d, "netstat").write_text(BAD64)
        env = {"PATH": "/usr/bin:/bin", "FIX_VMNET_ROUTE_FIXTURE_DIR": d}
        r = subprocess.run(["/bin/sh", str(SCRIPT)], check=False, env=env, capture_output=True, text=True)
    assert r.returncode == 0 and drylines(r) == ["DRYRUN " + D64, "DRYRUN " + A64]
