# Hard check 1 of the tendcf consent job, applied to the whole `config` of the host:
#   nix eval --json <flake>#nixosConfigurations.<host>.config --apply "$(cat check1.nix)"
# Result: { execdUnitPresent, hits, rawHits, packageHits, scriptHits, scanned }. The check
# passes when execdUnitPresent is false, the four hit lists are empty and `scanned` has exactly
# the five expected counts, all non-negative integers, four of them above zero (run.sh checks;
# the counts keep a mis-wired scan from passing vacuously).
#
# Each hit is { unit, why }: an item whose text names cf-execd or cf-agent, or that could not
# be evaluated (a field that cannot be read cannot be proven clear). It checks the effect
# (what the host would run), not the services.cfengine-tendcf knob.
#   hits        service and timer fields (Exec*, script, preStart ...) of systemd.services,
#               systemd.timers, systemd.user.services and systemd.user.timers
#   rawHits     the rendered text of every systemd.units and systemd.user.units entry, and
#               environment.etc entries that install a unit (target systemd/..., name and text)
#   packageHits systemd.packages: the package name (cfengine or tendcf), and the text of every
#               file under ${pkg}/lib/systemd/system and ${pkg}/lib/systemd/user: regular files,
#               drop-ins in subdirectories and symlinks (read through the link). Reading a
#               package's files at eval is import-from-derivation: nix realises the package
#               first. The packages are substituted from the binary cache, and a package that
#               cannot be built or fetched fails the eval, which the check treats as a failure,
#               as it does a broken or looping symlink, a link to a directory or a special file.
#   scriptHits  system.activationScripts (string or .text), boot.postBootCommands,
#               systemd.tmpfiles.rules and services.cron.systemCronJobs
# Not covered (textual check, see docs/tendcf-consent.md): a wrapper that execs cf-agent
# indirectly, environment.etc entries given only as `source`, package files outside the two
# unit directories, and `systemd.tmpfiles.settings`.
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
  # is checked, and so is the text of every file a package ships under lib/systemd/system and
  # lib/systemd/user: regular files, files in subdirectories (drop-ins `x.service.d/*.conf`,
  # `*.wants/`), and symlinks (read through the link, whatever its target; Nix has no readlink,
  # so a link into the package and one outside it are read the same way).
  # A symlink that is broken, loops or points at a directory, and an entry that is neither a
  # file, a directory nor a symlink, aborts the eval, which the check treats as a failure:
  # `builtins.readFile` errors are not catchable, so nothing unreadable is skipped.
  pkgName = p: p.pname or p.name or "?";
  unitDirs = [
    "lib/systemd/system"
    "lib/systemd/user"
  ];
  # Every non-directory entry below `root`/`rel` as a path relative to `root`, descending into
  # real directories only (a symlink is never followed as a directory, so there is no cycle).
  entriesUnder =
    root: rel:
    let
      dir = if rel == "" then root else "${root}/${rel}";
      kinds = builtins.readDir dir;
    in
    builtins.concatMap (
      n:
      let
        r = if rel == "" then n else "${rel}/${n}";
      in
      if kinds.${n} == "directory" then
        entriesUnder root r
      else if kinds.${n} == "regular" || kinds.${n} == "symlink" then
        [ r ]
      else
        throw "unreadable entry (${kinds.${n}}): ${root}/${r}"
    ) (builtins.attrNames kinds);
  shippedFiles =
    p:
    builtins.concatMap (
      d:
      if builtins.pathExists "${p}/${d}" then
        map (f: "${d}/${f}") (entriesUnder "${p}/${d}" "")
      else
        [ ]
    ) unitDirs;
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
    ++ builtins.concatMap (f: hit "packages.${pkgName p}/${f}" (builtins.readFile "${p}/${f}")) (
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
  # What was looked at. services, units, activationScripts and etc are above zero on any real
  # NixOS host, so a scan wired to the wrong attribute and seeing nothing cannot pass (run.sh
  # requires them > 0). packageFiles can legitimately be zero (no packages, or none with unit
  # files), and an enumeration or read failure aborts the eval instead of lowering it.
  scanned = {
    services = count (builtins.attrNames systemd.services);
    units = count (builtins.attrNames systemd.units);
    activationScripts = count (builtins.attrNames activation);
    etc = count (builtins.attrNames config.environment.etc);
    packageFiles = count (builtins.concatMap shippedFiles systemd.packages);
  };
}
