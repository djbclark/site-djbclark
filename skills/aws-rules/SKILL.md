---
name: aws-rules
description: >-
  AWS Agent Toolkit working rules (aws-mcp tools, `aws-agent` profile, skill
  lookup, verify-before-concluding, IaC, secret safety). Load only when a task
  touches an AWS account; never always-on.
---

# aws-rules — AWS guidance, loaded on demand

Upstream's `rules/aws-agent-rules.md` from
[aws/agent-toolkit-for-aws](https://github.com/aws/agent-toolkit-for-aws/blob/main/rules/aws-agent-rules.md)
(fetched 2026-10-29), kept here as a skill instead of in `AGENTS.md` by operator
ruling (djbclark, 2026-10-29: "use this very occasionally ... do not automatically
load it or dirty AGENTS.md"). Upstream's setup step 7 would append it to a rules
file; the global `~/.agents/AGENTS.md` is at its 14,000-byte cap.

## Local setup facts (2026-10-29)

- AWS CLI v2 at `~/.local/bin/aws`; credentials come from `aws login` (browser), profile
  **`aws-agent`**, default Region `us-east-1`. The account is the advanced (standard)
  experience: no AWS Settings project, no project Region limits.
- The Agent Toolkit service is `us-east-1` only; its calls always pass
  `--region us-east-1 --profile aws-agent`.
- The `aws-mcp` MCP server is `~/.local/bin/mcp-proxy-for-aws` (installed with `uv tool
  install mcp-proxy-for-aws`, 2026-10-29), called directly in each TUI's config instead of
  the generated `uvx mcp-proxy-for-aws@latest`: one process of about 50 MB, not the `uv`
  wrapper plus Python pair (about 175 MB at start). It no longer re-resolves `@latest` on
  launch; the nightly `brew-fast-upgrade` (03:10, `uv tool upgrade --all`) keeps it current,
  or run `uv tool upgrade mcp-proxy-for-aws` by hand. A running agent keeps the old
  binary until it restarts. Each entry sets
  `AWS_MCP_PROXY_PROFILES=aws-agent`; without it the server fails with
  `JSON-RPC error: -32602: Invalid request parameters("")`. Re-running
  `aws configure agent-toolkit` rewrites the entries back to `uvx`; redo both edits after it.
  Another account: `aws login --profile NAME`, add NAME to the space-separated
  `AWS_MCP_PROXY_PROFILES` in every MCP config, restart the TUI.
- 24 default AWS skills were installed by `aws configure agent-toolkit` (`aws-iam`,
  `aws-cdk`, `aws-storage`, ...); more: `aws agent-toolkit search-skills --search-query TEXT`.
- **`aws-agent` is the account root user, on purpose** (operator, 2026-10-29): the browser
  login bound the profile to root, and root stays. An IAM policy cannot deny root, and the
  account is in no AWS Organization, so no SCP either.
- **Bedrock inference access is OFF since 2026-10-29** (operator ruling; gating to be
  decided in [issue 141](https://github.com/djbclark/djbclark-ade/issues/141)): the Bedrock
  API key's IAM user `BedrockAPIKey-hwut` has its service credential `Inactive` and an inline
  `Deny bedrock:*` policy, so the vault token `AWS_BEARER_TOKEN_BEDROCK` answers 403. Root
  (and so `aws-mcp` and the `aws-agent` profile) can still call Bedrock; do not invoke Bedrock
  models unless asked. Re-enable steps are in the issue.
- Re-sync this file: re-fetch the upstream URL above and replace the rules section below.

## Precedence

Where these rules conflict with this machine's own instructions, the machine's win.
In particular, secrets stay on `sudo-secretspec` (`~/.agents/AGENTS.md` item 6); the
Secret Safety section below applies only to AWS Secrets Manager.

## Rules (upstream, verbatim)

- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- For any AWS task or question — building, configuring, migrating, debugging,
  or operating a service, writing SDK code, authoring CDK/CloudFormation, or
  answering how a service works — first call `aws___search_documentation` with
  topic `agent_skills` and load the matching skill with `aws___retrieve_skill`.
  Do this even when you believe you know the answer: skills carry current
  service behavior that your training may not. Prefer the skill's guidance over
  general knowledge. Skip it only for work that does not involve AWS.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- Before reporting a count, a total, or that something does not exist, read
  every page of the results and search every Region and scope where it could
  be. If you could not, say the result is partial and name what you checked.
- To say what a system currently does, read what the runtime uses: the
  completed deployment, the alias or version that is invoked, the template the
  stack is running. A newer stored version, a draft, or a description field is
  not evidence of live behavior.
- Present a cause as confirmed only if data, configuration, or logs you read
  show it. Label anything else as unverified, and say what you would check
  next.
- When the user asks a specific question or names a suspected cause, confirm
  or rule out each cause they raised, and do not offer alternatives your evidence
  does not support.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

### Before you conclude

- Before deciding the AWS account can't hold what the request asks for,
  look. List the places it could live, such as S3 buckets, databases, and
  log groups, and read what is there.
- Don't conclude that records are missing from metadata, such as a
  creation date or a stored-bytes count, or from one query that failed or
  came back empty. Read the records another way, across the full time
  range, before reporting them absent.

### Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.
