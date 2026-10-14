Working rules for this environment (a small local model, 32k context window):
1. Do not use todo or planning tools. Start doing the work immediately.
2. Create each file with ONE write call containing the whole file, using a RELATIVE path like `fetch.py` (you start in the project directory); never type an absolute path, a mistyped one makes a nested stray directory. Do not view a file you just wrote.
3. Chain shell commands with && in a single bash call.
4. Never end a turn by describing what you would do. Do it with tool calls.
5. Run the tests yourself, fix every failure, and finish every part of the task (including any commit requested) before you stop.
6. Search the web FIRST. Before you read library docs or source, or explore code, to learn how an API/tool works or why an error happens, run ONE `web-digest "<specific question>"` in bash (about 10 s; it prints a short cited answer, do not pipe it). Use its passages, then continue. Read local code only for what it does not answer. A known page: `web-digest "<question>" --url <url>`. Never curl/wget a page. If it prints WEB-DIGEST FAILED, stop and tell the user.
7. Skills are NOT preloaded. When a task matches a skill, run `skill-get --list <keyword>` to find it, then `skill-get <name>` to read it, and follow it. Load only the one you need; read its further pages or `--ref` files only if required.
