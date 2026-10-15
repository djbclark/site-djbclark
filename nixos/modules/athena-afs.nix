# OpenAFS client and Athena tickets pushed from the Mac (phase B of
# docs/plans/vps-primary-athena.md; decisions 1.4 and 1.5).
#
# There is no Kerberos password login here, so tickets arrive from the Mac:
# its hourly athena-kinit job (macos/athena-kerberos/athena-kinit) sends a
# renewable TGT over ssh with a key that can do nothing but run
# athena-tgt-receive. The receiver installs it as djbclark's cache and runs
# aklog. When the Mac is asleep, athena-tgt-renew keeps the ticket and the AFS
# tokens alive up to the ticket's renewable life (7 days).
#
# Tokens are set without a PAG, so every djbclark process sees them.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  ccRoot = "/var/lib/krb5cc";
  uid = toString config.users.users.djbclark.uid;
  cache = "${ccRoot}/${uid}/tgt";
  afs = config.services.openafsClient.packages.programs;
  tools = lib.makeBinPath [
    pkgs.coreutils
    pkgs.gnugrep
    pkgs.krb5
    afs
  ];
  receive = pkgs.writeShellScript "athena-tgt-receive" ''
    set -euo pipefail
    export PATH=${tools}
    umask 077
    t=$(mktemp ${ccRoot}/${uid}/incoming.XXXXXX)
    trap 'rm -f "$t"' EXIT
    head -c 65536 > "$t"
    # Only a valid djbclark@ATHENA.MIT.EDU TGT replaces the cache.
    klist -s -c "FILE:$t"
    klist -c "FILE:$t" | grep -qx 'Default principal: djbclark@ATHENA.MIT.EDU'
    klist -c "FILE:$t" | grep -q 'krbtgt/ATHENA.MIT.EDU@ATHENA.MIT.EDU'
    mv -f "$t" ${cache}
    trap - EXIT
    KRB5CCNAME=FILE:${cache} aklog
    echo ok
  '';
in
{
  services.openafsClient = {
    enable = true; # cellName athena.mit.edu comes from nixathena
    cache.blocks = 3000000; # KiB, about 2.9 GiB on the root disk
  };

  # A file cache the push can replace and the renew timer can rewrite (the
  # nixathena default is the kernel keyring, which suits pam_krb5 logins).
  security.krb5.settings.libdefaults.default_ccache_name = lib.mkForce "FILE:${ccRoot}/%{uid}/tgt";
  systemd.tmpfiles.rules = [
    "d ${ccRoot} 0755 root root -"
    "d ${ccRoot}/${uid} 0700 djbclark users -"
  ];

  # The Mac's push key: no pty, no forwarding, only from the Mac's tailnet address.
  users.users.djbclark.openssh.authorizedKeys.keys = [
    ''restrict,from="100.113.53.87",command="${receive}" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAhjpIb8xyRFKfrYvZuwsaH4GgV/ViZfvq5XoNn3SgRy djbclark@mac-athena-tgt-push''
  ];

  systemd.services.athena-tgt-renew = {
    description = "Renew djbclark's Athena TGT and AFS tokens";
    after = [ "openafs-client.service" ];
    unitConfig.ConditionPathExists = cache;
    environment.KRB5CCNAME = "FILE:${cache}";
    path = [
      pkgs.krb5
      afs
    ];
    serviceConfig = {
      Type = "oneshot";
      User = "djbclark";
    };
    # An expired ticket is not an error here: the next push from the Mac fixes it.
    script = ''
      klist -s || exit 0
      kinit -R
      aklog
    '';
  };
  systemd.timers.athena-tgt-renew = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 00/4:17:00";
      Persistent = true;
    };
  };
}
