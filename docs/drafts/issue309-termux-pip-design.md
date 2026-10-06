## 1. On-Device Python Footprint (The Facts)

The device-side Python scripts driven by this repo are genuinely stdlib-only. The previous audit is correct. The fleet does not currently ship or depend on any third-party Python packages for its on-device tooling.

**Device scripts pushed/executed:**
- `device/termux/py/start_adb.py` (imports `os`, `shlex`, `signal`, `subprocess`, `sys`, `time`, `shutil`)
- `device/termux/py/stayturgid_repair.py` (imports `base64`, `datetime`, `fcntl`, `json`, `os`, `re`, `subprocess`, `sys`, `time`)
- `device/termux/py/stayturgid_screen_control.py` (imports `os`, `re`, `subprocess`, `sys`, `threading`, `time`)
- `device/termux/py/stayturgid_agent_presence.py`, `stayturgid_battery_alarm.py`, `stayturgid_bridges.py`, `stayturgid_check_repo_version.py`, `stayturgid_handsets.py`, `stayturgid_peer_bootstrap.py`, `stayturgid_peer_help.py`, `stayturgid_peer_keepalive.py`, `stayturgid_rish.py`, `stayturgid_screen_awake_guard.py`, `stayturgid_shell.py`
- `ansible_collections/stayturgid/firerpa/roles/firerpa/files/firerpa_lifecycle.py` and `firerpa_service_patch.py` (import `argparse`, `hashlib`, `tarfile`, `zipfile`, `zlib`, etc.)

**Local modules pushed alongside them:**
- `control/lib/termux_api.py`, `control/lib/ui_clearance.py`, `control/lib/a11y_services.py`, `control/lib/ui_guard.py`, `control/lib/ui_parse.py` are pushed directly as individual files to `~/.stayturgid/lib/` or alongside scripts. They also only use stdlib modules (e.g. `re`, `json`, `subprocess`).

*(Note: `cache_otelcol.py` is executed on the control node via `delegate_to: localhost`, and the otelcol wrapper pushed to the device is `start-otelcol.sh.j2`, a bash script.)*

## 2. The Existing apt/pkg Pattern

The current Termux `apt` package layer does the three jobs gracefully:
1. **Declaration:** A YAML list in `ansible_collections/stayturgid/termux/roles/termux_userland/defaults/main.yml` named `stayturgid_termux_packages` (lines ~17-31).
2. **Convergence:** A custom Ansible module `stayturgid.termux.termux_pkg` (source at `ansible_collections/stayturgid/termux/plugins/modules/termux_pkg.py`) is invoked in `tasks/main.yml` to install packages cleanly while respecting check mode.
3. **Update Monitor:** A script at `control/bin/check_termux_pkg_updates.py` runs on the control node. It iterates devices from the inventory, SSHes in to run `apt list --upgradable`, caches results in `~/.local/state/stayturgid/termux-pkg-updates.json`, and sends a Hermes Telegram alert if the pending update set changes. 

**Offline Handling:** The update monitor gracefully handles unreachable devices by catching `subprocess.TimeoutExpired` and `OSError` during SSH, skipping the device as a non-fatal error to preserve its last known state without breaking the loop.

---

## 3. Proposed Designs

### Design A: The "Custom Sibling Module" (Mimics `termux_pkg`)
* **Declaration:** Add `stayturgid_termux_pip_packages` (list) to `defaults/main.yml`.
* **Convergence:** Create a custom module `stayturgid.termux.termux_pip` in `plugins/modules/termux_pip.py`, mirroring `termux_pkg`. It shells out to `pip list --format=json` for state calculation, and `pip install` for convergence. Invoked in `tasks/main.yml`.
* **Auditor/Monitor:** Create `control/bin/check_termux_pip_updates.py`, cloning the pkg monitor's structure but running `pip list --outdated --format=json` over SSH and storing in `termux-pip-updates.json`.
* **Unreachable Behavior:** The Python monitor catches SSH timeouts as non-fatal skips, exactly like the apt monitor.
* **Control Node Testing:** Unit tests in `test_termux_pip.py` mock `AnsibleModule.run_command` (returning fake `pip list` JSON), perfectly verifying `deploy-check` check-mode without touching a device or network.
* **Index Drift Failure:** The custom module catches non-zero `pip install` exit codes, returning a structured failure for that task without crashing Ansible's parser.

### Design B: The "Ansible Builtin" Approach
* **Declaration:** `stayturgid_termux_pip_packages` in `defaults/main.yml`.
* **Convergence:** A task in `tasks/main.yml` using `ansible.builtin.pip` with `executable: "{{ termux_prefix }}/bin/pip"` and `name: "{{ stayturgid_termux_pip_packages }}"`. If Termux enforces PEP 668, it uses `extra_args: "--break-system-packages"`.
* **Auditor/Monitor:** `control/bin/check_termux_pip_updates.py` (same as Design A).
* **Unreachable Behavior:** Same SSH timeout catching.
* **Control Node Testing:** Relies on `ansible.builtin.pip`'s native check-mode support.
* **Index Drift Failure:** Standard Ansible failure on the task.

### Design C: The "Requirements Sync" Approach
* **Declaration:** A literal `device/termux/requirements.txt` file tracked in Git.
* **Convergence:** An `ansible.builtin.copy` task pushes the file to `~/.stayturgid/requirements.txt`. A subsequent `ansible.builtin.command` runs `pip install -r ~/.stayturgid/requirements.txt`.
* **Auditor/Monitor:** `check_termux_pip_updates.py` parses `pip list --outdated` via SSH.
* **Unreachable Behavior:** Same SSH timeout catching.
* **Control Node Testing:** Testable manually via scripts, but fails Ansible's `check_mode`.
* **Index Drift Failure:** `ansible.builtin.command` fails with stderr output natively.

---

## 4. Recommendation

I recommend **Design A (The Custom Sibling Module)**. It establishes a true sibling to the existing `termux_pkg` system. More importantly, it respects the non-negotiable `deploy-check` story: you can write mock-driven unit tests for `test_termux_pip.py` (mirroring `test_termux_pkg.py`) to guarantee flawless dry-runs on the Mac without a live device.

**What NOT to do:** Do NOT use **Design C (Requirements Sync)**. Wrapping `pip install -r` in a raw `ansible.builtin.command` task directly fights the `just deploy-check` dry-run story. Ansible `command` tasks do not know if they *would* change state natively. You would be forced to either accept false `changed=true` results in dry runs, or write complex, brittle `changed_when`/`check_mode` parsing logic around `pip freeze` just to support dry runs. 

While Design B (Ansible Builtin) is tempting, `ansible.builtin.pip` can be opaque in check-mode (sometimes hitting the network to check versions), and passing `--break-system-packages` in task kwargs leaks Termux-specific environment details into the playbook instead of containing them in a module.

---

## 5. Unknowns (Requires a Live Device)
1. **Pip availability:** Does the `python` apt package in Termux provide `pip` by default, or must we add `python-pip` to `stayturgid_termux_packages`?
2. **PEP 668 enforcement:** Does `pip install` in this specific Termux environment enforce PEP 668? Will the convergence module need to implicitly append `--break-system-packages`, or should we deploy a global `venv` under `~/.stayturgid/venv`?
3. **C Extensions:** If any targeted Python packages require compilation (e.g., no cross-compiled Android `aarch64` wheels are available), we would need to determine if `clang`, `make`, and `python-dev` must be added to `stayturgid_termux_packages` to compile them on-device.
