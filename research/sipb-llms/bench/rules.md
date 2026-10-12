Working rules for this environment (a small local model, 32k context window):
1. Do not use todo or planning tools. Start doing the work immediately.
2. Create each file with ONE write call containing the whole file. Do not view a file you just wrote.
3. Chain shell commands with && in a single bash call.
4. Never end a turn by describing what you would do. Do it with tool calls.
5. Run the tests yourself, fix every failure, and finish every part of the task (including any commit requested) before you stop.
