# Gradle limits and the bg load gate

This Mac has 8 cores (4 performance, 4 efficiency) and 16 GB. One unbounded R8 release
build ran 112 threads on 2026-10-05 and drove the load average past 130, and with
several agents building at once everything slowed down.

## Pieces

1. **Profiles** in `gradle/profiles/`: `low` is the default, `night` is for unattended
   overnight work. Every Gradle home's `gradle.properties` links to
   `~/.local/state/gradle-limits/gradle.properties`, which links to the active profile. A
   user-level gradle.properties overrides each project's own.
2. **`bin/gradle-limits`**: `status`, `set night --until 07:00` (or `--for 8h`), `low`,
   `check` (revert an expired profile), and `link` (repair the Gradle home links). A
   non-default profile always needs an expiry.
3. **`bin/bg`**: starts work at utility QoS. It first waits while the 1-minute load per core
   is above `BG_MAX_LOAD_PER_CORE` (default 1.5), for at most `BG_LOAD_WAIT` seconds (default
   900), then starts anyway. `BG_LOAD_WAIT=0` skips the wait. It also runs
   `gradle-limits check`.
4. **Gradle slots in `bg`**: a `bg` command that runs `gradle`/`gradlew` (also behind
   `env VAR=… ./gradlew`) takes one of `BG_GRADLE_SLOTS` machine-wide slots (default 2) for its
   whole run, waiting up to `BG_GRADLE_WAIT` seconds (default 1800). Slots are `shlock` files
   under `~/.local/state/bg/gradle-slots/`; a dead pid frees its slot. Only builds started
   through `bg` are counted, so an agent calling `./gradlew` directly bypasses the cap.

## Memory (2026-10-06)

On 2026-10-06 eight agents were building Pastiera worktrees at once. Each started its own
daemon at `-Xmx4g`, plus a Kotlin daemon, and the 16 GB Mac sat 11 GB deep in swap. Most of
the "disk load" was paging: about 25k page decompressions per second and 6-8k small I/O
operations per second on the SSD. Changes:

1. Heap `-Xmx2g` in `low` (3g in `night`). Pastiera and ShizukuTendCF ask for 2g themselves.
2. `-XX:G1PeriodicGCInterval=60000 -XX:MinHeapFreeRatio=10 -XX:MaxHeapFreeRatio=30`: an idle
   daemon gives freed heap back to the OS. **Min must be set with Max**: Max=30 alone fails
   against the default Min of 40, and the JVM refuses to start. Test any new flag with
   `java <args> -version` on JDK 21 and 25 before it goes live.
3. Daemon idle timeout of 10 min; the Kotlin daemon gets the same through
   `-Dkotlin.daemon.jvm.options=autoshutdownIdleSeconds=600`.
4. `GRADLE_USER_HOME` moved from the USB stick to `~/.cache/gradle`. The USB stick serves
   Gradle's many small random reads badly. `~/.bashrc` switches once the marker
   `~/.cache/gradle/.moved-from-usb` exists. The old USB path becomes a symlink, so shells
   started before the switch keep working.

## Notes

1. A profile switch only affects daemons started after it. Idle daemons exit after 10 min
   (`org.gradle.daemon.idletimeout`), so old settings don't linger.
2. `-XX:ActiveProcessorCount` caps the thread pools inside the daemon JVM (R8, D8, the
   compiler, GC). That cap is what actually bounds a release build. `org.gradle.workers.max`
   alone does not.
3. Don't override the profile per build with `--max-workers` or `-Dorg.gradle.*`.

## Benchmark

First run, 2026-10-06 ~03:30 (`:manager:minifyDropinReleaseWithR8 --rerun`, `--no-daemon`, ShizukuTendCF):

| Visible CPUs / workers | Wall time | Load avg / max |
|---|---|---|
| 2 | 454 s | 30.3 / 42.0 |
| 4 | 981 s | 67.9 / 97.6 |
| 6 | 519 s | 34.2 / 48.8 |
| 8 | 315 s | 40.3 / 46.2 |

**First run inconclusive.** The machine was not idle: `suggestd` (~0.9 core; see the todo about it) and the
nightly `plocate-updatedb` (~0.8 core, 35 min) ran throughout, and the load average was already
30+. The order of the runs, not the setting, dominates these numbers. `night` stays at 4/4 until a
re-run on a quiet machine (check `uptime` first; load under ~4), ideally 2-3 runs per setting.

Second run, 2026-10-06 05:12 on a quiet machine (load ~2 before; one pass):

| Visible CPUs / workers | Wall time | vs 2 | Load avg / max |
|---|---|---|---|
| 2 | 174 s | n/a | 4.0 / 4.9 |
| 4 | 165 s | -5% | 7.5 / 11.2 |
| 6 | 151 s | -13% | 7.9 / 10.1 |
| 8 | 140 s | -20% | 11.5 / 14.3 |

R8 is largely sequential: 2 -> 8 CPUs saves 20% while load nearly triples, and 8 pushes the
peak to ~1.8 per core, past bg's gate. **`night` uses 6 visible CPUs** (13% faster at about one
load per core) with 4 parallel workers; `low` stays at 2 for daytime. One pass only; a second
pass per setting would tighten the numbers.
