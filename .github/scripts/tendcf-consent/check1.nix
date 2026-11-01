# Hard check 1 of the tendcf consent job, applied to `config.systemd` of the host:
#   nix eval --json <flake>#nixosConfigurations.<host>.config.systemd --apply "$(cat check1.nix)"
# Result: { execdUnitPresent, hits }. The check passes when execdUnitPresent is false and
# hits is empty (run.sh checks).
#
# hits lists every unit in systemd.services or systemd.timers whose start commands or script
# name cf-execd or cf-agent, and every field that cannot be evaluated (a command that cannot
# be read cannot be proven clear). It checks the effect (what the host would run), not the
# services.cfengine-tendcf knob.
systemd:
let
  naming = s: builtins.length (builtins.split "cf-(execd|agent)" s) > 1;
  # The text of one field. Context is dropped so store paths read as plain text and nothing
  # is realised; null means the field could not be evaluated.
  text =
    v:
    let
      r = builtins.tryEval (builtins.unsafeDiscardStringContext (builtins.toJSON v));
    in
    if r.success then r.value else null;
  execFields = [
    "ExecStart"
    "ExecStartPre"
    "ExecStartPost"
    "ExecStop"
    "ExecStopPost"
    "ExecReload"
  ];
  scriptFields = [
    "script"
    "preStart"
    "postStart"
    "preStop"
    "postStop"
    "reload"
  ];
  scan =
    kind: units:
    builtins.concatMap (
      name:
      let
        u = units.${name};
        sc = u.serviceConfig or { };
        probes =
          (map (f: {
            field = f;
            value = sc.${f} or null;
          }) execFields)
          ++ (map (f: {
            field = f;
            value = u.${f} or null;
          }) scriptFields);
      in
      builtins.concatMap (
        p:
        let
          t = if p.value == null then "" else text p.value;
          id = "${kind}.${name}.${p.field}";
        in
        if t == null then
          [
            {
              unit = id;
              why = "unevaluable";
            }
          ]
        else if naming t then
          [
            {
              unit = id;
              why = "names cf-execd or cf-agent";
            }
          ]
        else
          [ ]
      ) probes
    ) (builtins.attrNames units);
in
{
  execdUnitPresent = systemd.services ? "cfengine-tendcf-execd";
  hits = scan "services" systemd.services ++ scan "timers" systemd.timers;
}
