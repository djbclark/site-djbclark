### Fixed

- `roles/sudo_ask_grant/files/sudo-ask-grant-setup.sh` now renders `$BIN revoke` instead of `$BIN revoke ""` in `/etc/sudoers.d/sudo-ask-grant`. In `sudoers(5)`, `""` means no arguments only as the sole argument (`command ""`); after `revoke`, it required a literal second empty argument, causing `sudo -n /usr/local/libexec/sudo-ask-granted revoke` to be refused during `--verify --live` and triggering rollback. Writing `$BIN revoke` with no wildcard matches `revoke` with zero extra arguments while still refusing `revoke extra`. (#309)
