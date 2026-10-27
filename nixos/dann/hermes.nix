# The entity's five gifted AI pools, served from the entity's own host.
#
# Green light: dann-fa83e3d72734 (lead, 2026-10-27) — Option A, the declarative NixOS module
# (`nixosModules.default` from github:djbclark/hermes-agent), never the `curl | bash` installer.
# Plan and per-pool verification: keeper-8a2199e643f6, correction keeper-888dbe4481fd.
#
# WHY THE CREDENTIALS LIVE IN /run/secrets AND NOT HERE: this repo is public and the Nix store is
# world-readable. The five API keys come from sops (`nixos/dann/secrets/pools.yaml`, age recipient
# = the host's own key only) and reach Hermes as *runtime* paths in `environmentFiles`, which the
# module's activation appends to $HERMES_HOME/.env. Nothing secret reaches the store.
#
# WHY EACH SECRET FILE IS A `NAME=value` LINE RATHER THAN A BARE VALUE: `environmentFiles` wants
# .env syntax, so storing the assignment next to the value keeps one file per credential (rotating
# one key touches one line), needs no `sops.templates`/`sops.placeholder` indirection, and keeps
# every declared file self-describing. Verified shape of that option in nix/moduleCommon.nix:292.
#
# POOL POLICIES (binding, per the pool task):
#   1. opencode-go pools follow ~/src/djbclark-ade/config/go-model-policy.json. The routine tier is
#      exposed here and the advisory tier is NOT: with no gating in front of them, listing advisory
#      ids would invite an advisory-class call at routine effort. The one policy id Go does not
#      serve (`deepseek-v4-flash`) is absent rather than listed-and-404.
#   2. The two Go subscriptions are separate provider entries (`opencode-go-<account>`) so their
#      usage windows are counted apart. Naming them `opencode-go*` is what routes them through the
#      family's per-model api_mode, /v1 normalisation and `x-opencode-session` header
#      (hermes_cli/models.py:2527, agent/opencode_affinity.py).
#   3. The unlabelled `OPENCODE_GO_API_KEY` in the Mac vault is deliberately NOT here: the lead
#      retired it (it duplicates one of the two labelled accounts) — dann-fa83e3d72734 §2.
#   4. clinepass model ids are `cline2-pass/*`: the `cline-pass/*` namespace 404s on this relay
#      (probed 2026-10-27 from the Mac with both keys).
{ config, lib, ... }:

let
  # Routine tier ∩ the 38 ids the Go relay actually serves (catalogue pulled 2026-10-27 — both
  # keys return the identical list). 13 of the policy's 14.
  goRoutineModels = [
    "deepseek-v4.1-flash"
    "minimax-m3"
    "minimax-m3.1-flash"
    "glm-5.3-flash"
    "gpt-6-luna"
    "gpt-5.6-luna"
    "claude-haiku-5-5"
    "mimo-v2.6-flash"
    "mimo-v2.5"
    "qwen3.7-plus"
    "longcat-2.0"
    "hy3"
    "beam-free"
  ];

  # The list the Mac's working `cline2` provider block carries (the Go policy does not govern these;
  # clinepass is a separate product).
  clineModels = [
    "cline2-pass/kimi-k3"
    "cline2-pass/kimi-k2.7-code"
    "cline2-pass/kimi-k2.6"
    "cline2-pass/deepseek-v4-pro"
    "cline2-pass/deepseek-v4-flash"
    "cline2-pass/glm-5.2"
    "cline2-pass/mimo-v2.5-pro"
    "cline2-pass/mimo-v2.5"
    "cline2-pass/minimax-m3"
    "cline2-pass/qwen3.7-max"
    "cline2-pass/qwen3.7-plus"
  ];

  # One sops secret per credential, named after the environment variable it carries: the sops key
  # IS the env var name in secrets/pools.yaml, and its VALUE is the `NAME=value` line itself, so
  # the file needs no key/value indirection and stays readable when decrypted by hand.
  # FLAT NAMES ON PURPOSE: the name is also the /run/secrets/... path segment, and a flat name
  # cannot be misread as a nested lookup inside the YAML.
  poolSecrets = [
    "OPENCODE_GO_API_KEY_DJBCLARK"
    "OPENCODE_GO_API_KEY_TECHNOEUPHORA"
    "CLINE_API_KEY"
    "CLINE_PASS_KEY_2_TE"
    "AWS_BEARER_TOKEN_BEDROCK"
  ];
in
{
  # Declared HERE, next to the one consumer, rather than in configuration.nix: the rule in that
  # file's sops comment is that a secret is added only when a service on this host consumes it, and
  # this module is that service. All five live in one encrypted file so rotation is one `sops` edit.
  # root-owned 0400 is enough: only the module's system.activationScripts reads them, as root, to
  # write $HERMES_HOME/.env once per activation. The service itself reads .env, not these files.
  sops.secrets = lib.genAttrs poolSecrets (_: {
    sopsFile = ./secrets/pools.yaml;
    owner = "root";
    group = "root";
    mode = "0400";
  });

  # `dann` must be in the service group, and this is NOT cosmetic. `addToSystemPackages` exports
  # HERMES_HOME system-wide, but the module makes that tree hermes:hermes 2770 and config.yaml
  # 0660 (`.env` 0640) — so without membership the CLI running as `dann` cannot read the config it
  # has been pointed at, which is exactly how each pool gets verified. The module only adds this
  # membership itself in CONTAINER mode (nixosModules.nix:383), so native mode has to say it.
  users.users.dann.extraGroups = [ config.services.hermes-agent.group ];

  services.hermes-agent = {
    enable = true;

    # Puts `hermes` on the system PATH with HERMES_HOME pointing at the gateway's state dir, so a
    # shell session and the service share config, sessions and skills instead of splitting into two
    # installations. This is also how the per-pool verification runs (as `dann`, no separate home).
    addToSystemPackages = true;

    # NO `extraDependencyGroups`. It would look like the way to get boto3 for Bedrock, but it
    # makes things worse: the option overrides the package (moduleCommon.nix:679) to a variant
    # containing ONLY the named groups, and `packages.default` here is `full`, which already
    # carries bedrock — and fifteen other groups — from uv.lock (boto3 1.42.89, verified). So
    # naming bedrock would swap a cached package for an uncached, narrower one. Let the default
    # stand.

    environmentFiles = map (name: config.sops.secrets."${name}".path) poolSecrets;

    # Not secret, so it does not belong in sops. `agent/bedrock_adapter.py:385` reads
    # AWS_REGION → AWS_DEFAULT_REGION → botocore → us-east-1; this pins the gift's region.
    environment.AWS_REGION = "us-east-1";

    settings = {
      # Routine default, per go-model-policy.json. Advisory work belongs on the clinepass or
      # Bedrock entries until real gating exists.
      model = {
        provider = "opencode-go-djbc";
        default = "deepseek-v4.1-flash";
      };

      # Resilience across the pools rather than across vendors: each fallback is a routine-tier
      # model on a different subscription, so a spent window moves the run, not the cost class.
      fallback_providers = [
        {
          provider = "opencode-go-technoeuphora";
          model = "deepseek-v4.1-flash";
        }
        {
          provider = "cline-djbclark";
          model = "cline2-pass/deepseek-v4-flash";
        }
        {
          provider = "cline-technoeuphora";
          model = "cline2-pass/deepseek-v4-flash";
        }
      ];

      providers = {
        # ── Pool 1: opencode-go, djbclark account ──────────────────────────────────────
        # NO `transport`/`api_mode` ON THE GO ENTRIES, ON PURPOSE. Setting one makes
        # `runtime_provider_custom.py` skip the OpenCode family's per-model api_mode derivation
        # (`if family is not None and not custom_provider.get("api_mode")`) and pin the whole entry
        # to one wire — a 503 for any model on the other surface. Leaving it unset lets the family
        # pick chat_completions vs responses per model and normalise the /v1 suffix.
        opencode-go-djbc = {
          name = "OpenCode Go (djbclark)";
          base_url = "https://opencode.ai/zen/go/v1";
          key_env = "OPENCODE_GO_API_KEY_DJBCLARK";
          default_model = "deepseek-v4.1-flash";
          discover_models = false;
          models = goRoutineModels;
        };

        # ── Pool 2: opencode-go, technoeuphora account ─────────────────────────────────
        opencode-go-technoeuphora = {
          name = "OpenCode Go (technoeuphora)";
          base_url = "https://opencode.ai/zen/go/v1";
          key_env = "OPENCODE_GO_API_KEY_TECHNOEUPHORA";
          default_model = "deepseek-v4.1-flash";
          discover_models = false;
          models = goRoutineModels;
        };

        # ── Pool 3: clinepass, djbclark account ────────────────────────────────────────
        cline-djbclark = {
          name = "Cline (djbclark)";
          api = "https://api.cline.bot/api/v1";
          key_env = "CLINE_API_KEY";
          transport = "chat_completions";
          default_model = "cline2-pass/deepseek-v4-flash";
          discover_models = false;
          models = clineModels;
        };

        # ── Pool 4: clinepass, technoeuphora account ───────────────────────────────────
        cline-technoeuphora = {
          name = "Cline (technoeuphora)";
          api = "https://api.cline.bot/api/v1";
          key_env = "CLINE_PASS_KEY_2_TE";
          transport = "chat_completions";
          default_model = "cline2-pass/deepseek-v4-flash";
          discover_models = false;
          models = clineModels;
        };

        # ── Pool 5 (Bedrock) is a BUILT-IN provider: no entry here ─────────────────────
        # `bedrock` needs no `providers` block — it is registered in hermes_cli/auth.py:242, reads
        # AWS_BEARER_TOKEN_BEDROCK from the env file, and its region comes from AWS_REGION above
        # (+ the `bedrock.region` mirror the auth gate checks). Adding a fake block would shadow it.
      };

      # Mirrors AWS_REGION for the auth gate at hermes_cli/auth.py:1332, which decides "is bedrock
      # configured?" from config.yaml rather than the environment.
      bedrock.region = "us-east-1";

      # The host is not a chat endpoint: no messaging platform is configured, so the gateway starts
      # and idles, and work arrives through the CLI. Left at defaults deliberately.
    };
  };
}
