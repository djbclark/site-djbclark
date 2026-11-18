{ pkgs }:
pkgs.testers.runNixOSTest {
  name = "ade-nats";
  nodes.machine = { lib, pkgs, ... }: {
    imports = [ ../modules/ade-nats.nix ];
    services.tailscale.enable = true;
    # This tests the broker's interface boundary, not Tailscale's control plane.
    # Live acceptance separately exercises two actual tailnet hosts.
    systemd.services.tailscaled.serviceConfig = {
      Type = lib.mkForce "simple";
      # Tailscale ships an upstream unit: reset its ExecStart before replacing it.
      ExecStart = lib.mkForce [ "" "${pkgs.coreutils}/bin/sleep infinity" ];
    };
    services.ade-nats = {
      enable = true;
      listenAddress = "100.64.0.1";
    };
    environment.systemPackages = [ pkgs.natscli pkgs.curl pkgs.iproute2 ];
  };
  testScript = ''
    import base64
    import json
    import shlex

    start_all()
    machine.wait_for_unit("tailscaled.service")
    machine.succeed("ip link add tailscale0 type dummy")
    machine.succeed("ip addr add 100.64.0.1/32 dev tailscale0")
    machine.succeed("ip link set tailscale0 up")

    with subtest("missing runtime authentication fails closed"):
        machine.fail("systemctl is-active --quiet nats.service")

    # Deliberately public fixture, not a deployment credential.
    token = "ade-test-fixture-not-a-secret-0123456789"
    auth = json.dumps({"authorization": {"token": token}})
    machine.succeed("install -d -m 0700 /etc/credstore")
    machine.succeed("printf %s " + shlex.quote(auth) + " > /etc/credstore/ade-nats-auth.json")
    machine.succeed("chmod 0400 /etc/credstore/ade-nats-auth.json")
    machine.succeed("systemctl restart nats.service")
    machine.wait_for_unit("nats.service")
    machine.wait_until_succeeds("curl --fail --silent http://127.0.0.1:8222/healthz")
    cli = "nats --server=nats://100.64.0.1:4222 --token=" + token

    with subtest("only the tailnet address accepts clients"):
        listeners = machine.succeed("ss -H -ltn 'sport = :4222'")
        assert "100.64.0.1:4222" in listeners, listeners
        assert "0.0.0.0:4222" not in listeners and "*:4222" not in listeners
        monitor = machine.succeed("ss -H -ltn 'sport = :8222'")
        assert "127.0.0.1:8222" in monitor, monitor
        machine.fail("nats --server=nats://100.64.0.1:4222 account info")
        machine.succeed(cli + " account info")

    with subtest("file-backed stream survives a broker crash"):
        machine.succeed(cli + " stream add PROBE --subjects=probe --storage=file --replicas=1 --defaults --discard=new --max-msgs=100")
        machine.succeed(cli + " pub probe persist-me")
        # stream get exposes JSON, not a --raw mode. Verify actual stored bytes.
        message = json.loads(machine.succeed(cli + " stream get PROBE 1 --json"))
        assert base64.b64decode(message["data"], validate=True) == b"persist-me"
        machine.succeed("systemctl kill --signal=KILL nats.service")
        machine.wait_until_succeeds("systemctl is-active --quiet nats.service")
        machine.wait_until_succeeds(cli + " stream get PROBE 1 --json")
        message = json.loads(machine.succeed(cli + " stream get PROBE 1 --json"))
        assert base64.b64decode(message["data"], validate=True) == b"persist-me"
        machine.succeed("test $(stat -c %a /var/lib/nats) = 750")

    with subtest("invalid authentication cannot override listener policy"):
        bad = json.dumps({"authorization": {"token": token}, "host": "0.0.0.0"})
        machine.succeed("printf %s " + shlex.quote(bad) + " > /etc/credstore/ade-nats-auth.json")
        machine.succeed("systemctl restart nats.service || true")
        machine.wait_until_fails("systemctl is-active --quiet nats.service")
        machine.wait_until_fails("curl --fail --silent http://127.0.0.1:8222/healthz")
  '';
}
