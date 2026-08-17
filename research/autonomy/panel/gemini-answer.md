This is a research answer based on the state of the open-source agentic coding ecosystem as of mid-2026. 

I will state this plainly upfront: **A shrink-wrapped, open-source tool that perfectly matches your exact combination of requirements—specifically, one that natively orchestrates and rotates between consumer CLI wrappers (like `claude-code`, Gemini CLI, etc.) to evade API costs and manage rolling consumer subscription quotas—does NOT exist.** 

Major open-source projects assume you are using **commercial API keys** (via LiteLLM or direct integrations). They handle rate limits via standard exponential backoff (HTTP 429), not by tracking a 5-hour consumer subscription window and hot-swapping to a different vendor's CLI binary. To achieve that specific rotation, you would absolutely have to write your own custom daemon.

However, if you are willing to use standard API billing (or if you use an API proxy that masks your consumer accounts), here are the three most viable, actively maintained open-source projects that tackle the context exhaustion and unattended execution problems.

---

### Candidate 1: SWE-agent
*   **Name & URL:** SWE-agent (https://github.com/princeton-nlp/SWE-agent)
*   **License:** MIT
*   **Summary:** A system that takes a codebase and a GitHub issue, spins up an isolated sandbox, and uses an Agent-Computer Interface (ACI) to autonomously write and test a fix. It exits by submitting a pull request for your review.
*   **Maturity Signals:** Highly mature. ~15k+ stars, originated from Princeton NLP, regular releases, heavily utilized in enterprise benchmarks. 
*   **How it handles context exhaustion:** It prevents it from accumulating in the first place. Instead of giving the LLM raw `bash` access (which often results in a 50,000-token `grep` dump), it forces the LLM to use custom, paginated ACI commands (e.g., a custom search command that only returns file paths and line numbers). Furthermore, context is strictly scoped to a single Issue.
*   **Program vs. LLM:** The thing that never dies is a **Python program** running the agent loop.
*   **Durable State:** Lives entirely in **Git** and your **Issue Tracker**. 
*   **Quota/Rate-limit awareness:** Basic API backoff only. No rolling window awareness.
*   **Multi-vendor:** Supports major models via standard API configuration.
*   **Weaknesses:** It is terrible at open-ended "greenfield" exploration. It requires a concrete issue description to act upon. If the issue is vague, it will fail. 

### Candidate 2: OpenHands (formerly OpenDevin)
*   **Name & URL:** OpenHands (https://github.com/All-Hands-AI/OpenHands)
*   **License:** MIT
*   **Summary:** A full-fledged autonomous software engineer platform that operates inside a secure Docker sandbox, capable of planning, browsing documentation, and executing code to complete complex directives.
*   **Maturity Signals:** Extremely active. ~35k+ stars, multiple commits daily, backed by the All Hands AI startup, massive community.
*   **How it handles context exhaustion:** It uses a "Context Condenser." When the token limit approaches a threshold, the Python backend intercepts the memory array, summarizes older conversational turns and tool outputs into a condensed narrative, and drops the raw logs, allowing the agent to continue without losing the plot.
*   **Program vs. LLM:** The thing that never dies is a **Python/React daemon** (the orchestrator backend).
*   **Durable State:** Lives in the isolated Git workspace and local SQLite/JSON session logs.
*   **Quota/Rate-limit awareness:** Uses LiteLLM for routing and fallbacks, but has no native concept of "5-hour consumer subscription caps."
*   **Multi-vendor:** Excellent. Can route across Anthropic, OpenAI, Google, etc., via API keys.
*   **Weaknesses:** While it can run unattended, it is still primarily optimized for a "Task → Resolution" lifecycle. Leaving a single session running for 4 days unattended will likely still result in the model eventually "drifting" or getting stuck in a hallucinated tool-error loop, despite context condensation.

### Candidate 3: Aider (Architect/Editor Mode)
*   **Name & URL:** Aider (https://github.com/paul-gauthier/aider)
*   **License:** Apache 2.0
*   **Summary:** A terminal-native AI pair programmer that modifies files in your local git repository directly and commits changes upon success.
*   **Maturity Signals:** Very mature. ~20k+ stars, extremely active daily maintenance, heavily relied upon by senior engineers.
*   **How it handles context exhaustion:** Uses `tree-sitter` to build highly compressed "Repo Maps" (cstags) rather than loading full files. Recently, it relies on an Architect/Editor pattern: an "Architect" model plans the change, and a separate "Editor" model executes it. This isolates context, preventing the executor from being bogged down by the planning history.
*   **Program vs. LLM:** The thing that never dies is a **Python CLI program**.
*   **Durable State:** Strictly **Git**. Aider commits working states immediately. 
*   **Quota/Rate-limit awareness:** Standard API rate-limiting handling.
*   **Multi-vendor:** Superb API support. 
*   **Weaknesses:** By default, it is an interactive pair programmer. While you can run it headless (e.g., `aider --message "do X" --yes`), it fundamentally lacks a native "infinite background loop" daemon. To make it run continuously across multiple repos, you would have to write a bash script to feed it tasks.

---

### The Dominant Architectural Pattern (As of Aug 2026)

The idea of a single, omniscient LLM context window running infinitely is dead. It is widely recognized as the "goldfish problem." The dominant pattern today is **The Ephemeral Agent Loop**:
1. A durable host program (written in Go, Rust, or Python) pulls a task from a queue.
2. The host parses the required files and injects *only* those into a brand new, fresh context window.
3. The LLM executes the task, outputs a diff or bash commands, and verifies via tests.
4. The host program commits the work, **kills the LLM session entirely**, and restarts the loop with a fresh context window for the next task.

State is kept exclusively in Git, Markdown trackers (`project-state.md`), and issue trackers. Memory is externalized.

### What Genuinely Does NOT Exist Yet

1. **Consumer CLI Orchestrators:** There is no OSS tool that acts as a hypervisor for *other* consumer CLIs (like `claude-code` or `cursor-cli`). The OSS community builds for APIs. If you want to parasitize flat-rate consumer subscriptions to save money on API costs, you are entirely on your own to build the rotational shell wrappers.
2. **True "Fire and Forget" for Days:** No agent runs flawlessly for 72 hours on a single prompt. They all eventually hallucinate, break a test, and spend 400 iterations trying to fix a missing semicolon in the wrong file. Unattended success *requires* task-scoping.

### Top 3 Recommendations, Ranked

1. **SWE-agent:** This is the closest to your philosophical ideal. It matches your "human-gated integration" (it makes PRs) and your "verifiability" (it relies on tests and git diffs, not self-reports). To run it continuously, you don't keep the agent alive; you just queue up GitHub issues and let a cron job spawn a fresh SWE-agent for each issue. Context exhaustion is mathematically eliminated because the context is destroyed after every PR.
2. **OpenHands:** If you truly want a daemon that you can point at a local directory and say "build a microservice based on this markdown file," this is the most robust sandbox environment available. Just be prepared to use API keys rather than consumer CLIs.
3. **Aider (Scripted):** Even though you don't want to write your own scripts, Aider's AST-based Repo Map is the undisputed king of local macOS context management. Writing a 10-line bash script to feed it markdown tasks sequentially is significantly more reliable than trusting an overly complex multi-agent orchestrator.
