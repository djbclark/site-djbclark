# Hard check 1 of the tendcf consent job, applied to the whole `config` of the host:
#   nix eval --json <flake>#nixosConfigurations.<host>.config --apply "$(cat check1.nix)"
# Result: { execdUnitPresent, hits, rawHits, packageHits, scriptHits, scanned }. The check
# passes when execdUnitPresent is false, the four hit lists are empty and every `scanned`
# count is above zero (run.sh checks; the counts keep a mis-wired scan from passing vacuously).
#
# Each hit is { unit, why }: an item whose text names cf-execd or cf-agent, or that could not
# be evaluated (a field that cannot be read cannot be proven clear). It checks the effect
# (what the host would run), not the services.cfengine-tendcf knob.
#   hits        service and timer fields (Exec*, script, preStart ...) of systemd.services,
#               systemd.timers, systemd.user.services and systemd.user.timers
#   rawHits     the rendered text of every systemd.units and systemd.user.units entry, and
#               environment.etc entries that install a unit (target systemd/..., name and text)
#   packageHits systemd.packages: the package name (cfengine or tendcf), and the text of every
#               regular file in ${pkg}/lib/systemd/system. Reading a package's files at eval is
#               import-from-derivation: nix realises the package first. The packages are
#               substituted from the binary cache, and a package that cannot be built or fetched
#               fails the eval, which the check treats as a failure.
#   scriptHits  system.activationScripts (string or .text), boot.postBootCommands,
#               systemd.tmpfiles.rules and services.cron.systemCronJobs
# Not covered (textual check, see docs/tendcf-consent.md): a wrapper that execs cf-agent
# indirectly, environment.etc entries given only as `source`, unit symlinks that point outside
# their package, and `systemd.tmpfiles.settings`.
config:
let
  systemd = config.systemd;
  naming = s: builtins.length (builtins.split "cf-(execd|agent)" s) > 1;
  # The text of one field. Context is dropped so store paths read as plain text and nothing
  # is realised; null means the field could not be evaluated.
  text =
    v:
    let
      r = builtins.tryEval (builtins.unsafeDiscardStringContext (builtins.toJSON v));
    in
    if r.success then r.value else null;
  # [] when clear, one { unit, why } when `v` (any value, null = absent) names cf-execd or
  # cf-agent or cannot be evaluated.
  hit =
    id: v:
    let
      t = if v == null then "" else text v;
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
      [ ];
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
      builtins.concatMap (p: hit "${kind}.${name}.${p.field}" p.value) probes
    ) (builtins.attrNames units);
  # The rendered text of every unit, which covers raw `systemd.units."x.service".text`
  # units that never appear in systemd.services, and every Exec* line of services and timers.
  scanUnits =
    kind: units:
    builtins.concatMap (name: hit "${kind}.${name}.text" (units.${name}.text or "")) (
      builtins.attrNames units
    );
  # Units linked from packages (systemd.packages) are not in any of the sets above. The name
  # is checked, and so is the text of every unit file the package ships.
  pkgName = p: p.pname or p.name or "?";
  unitDir = p: "${p}/lib/systemd/system";
  shippedFiles =
    p:
    if builtins.pathExists (unitDir p) then
      builtins.filter (n: (builtins.readDir (unitDir p)).${n} == "regular") (
        builtins.attrNames (builtins.readDir (unitDir p))
      )
    else
      [ ];
  scanPackages = builtins.concatMap (
    p:
    (
      if builtins.length (builtins.split "cfengine|tendcf" (pkgName p)) > 1 then
        [
          {
            unit = "packages.${pkgName p}";
            why = "package name mentions cfengine or tendcf";
          }
        ]
      else
        [ ]
    )
    ++ builtins.concatMap (n: hit "packages.${pkgName p}/${n}" (builtins.readFile "${unitDir p}/${n}")) (
      shippedFiles p
    )
  ) systemd.packages;
  # An activation script is a string or { text, deps }. The `script` entry is the module
  # system's rendering of all the others, so scanning the entries covers it.
  entryText = v: if builtins.isAttrs v then v.text or "" else v;
  activation = builtins.removeAttrs config.system.activationScripts [ "script" ];
  scanActivation = builtins.concatMap (
    n: hit "activationScripts.${n}" (entryText activation.${n})
  ) (builtins.attrNames activation);
  # environment.etc entries that install into systemd/ (a unit or a drop-in): target and text.
  etcUnits = builtins.filter (
    n: (builtins.substring 0 8 (config.environment.etc.${n}.target or n)) == "systemd/"
  ) (builtins.attrNames config.environment.etc);
  scanEtc = builtins.concatMap (
    n:
    let
      e = config.environment.etc.${n};
    in
    hit "etc.${n}" [
      (e.target or n)
      (e.text or "")
    ]
  ) etcUnits;
  hostScripts =
    hit "boot.postBootCommands" config.boot.postBootCommands
    ++ hit "systemd.tmpfiles.rules" systemd.tmpfiles.rules
    ++ hit "services.cron.systemCronJobs" config.services.cron.systemCronJobs;
  count = builtins.length;
in
{
  execdUnitPresent = systemd.services ? "cfengine-tendcf-execd";
  hits =
    scan "services" systemd.services
    ++ scan "timers" systemd.timers
    ++ scan "user.services" systemd.user.services
    ++ scan "user.timers" systemd.user.timers;
  rawHits = scanUnits "units" systemd.units ++ scanUnits "user.units" systemd.user.units ++ scanEtc;
  packageHits = scanPackages;
  scriptHits = scanActivation ++ hostScripts;
  # What was looked at. Each count is above zero on any real NixOS host, so a scan that was
  # wired to the wrong attribute and saw nothing cannot pass (run.sh requires them all > 0).
  scanned = {
    services = count (builtins.attrNames systemd.services);
    units = count (builtins.attrNames systemd.units);
    activationScripts = count (builtins.attrNames activation);
    etc = count (builtins.attrNames config.environment.etc);
    packageFiles = count (builtins.concatMap shippedFiles systemd.packages);
  };
}
