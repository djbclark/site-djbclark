#!/usr/bin/env python3
"""neofinder-stub-export.py — populate a staging volume with NeoFinder stubs.

For every item in the chosen NeoFinder catalogue(s), write an entry at
<dest>/<catalogue name>/<original relative path>: a directory for a catalogued
folder; for a catalogued file, a Finder ALIAS to the real file when it exists
on its mounted volume (opening the alias opens the real file; it carries the
real file's creation, modification and added dates and kind, header O), else
an empty STUB with mtime set to the catalogued modification date; and on
every entry a Finder comment (com.apple.metadata:kMDItemFinderComment,
which Spotlight indexes) carrying the original complete path, size and kind.
`macos/neofinder/neofinder-spotlight-batch.sh` then brings Spotlight up briefly and
indexes only that staging volume. The goal is for Finder search to stand in
for Spotlight's own index of the MOUNTED volumes, which stay unindexed
(`mdutil -a -i off`), so no resident indexer ever scans the real volumes.
Known gaps against that goal: the index exists only during the batch window,
and a search result is an alias to the real file (a stub when the file's
volume was not mounted at export time).

NeoFinder is only ever QUERIED over AppleScript. This script contains no
`set <property> of` on anything, and never calls delete/move/make/catalog/
update: the export is strictly read-only on the NeoFinder side.

Usage:
  neofinder-stub-export.py [export] [--dest DIR] [--catalog NAME]...
                          [--all] [--offline] [--page N] [--limit N]
                          [--progress] [--log FILE] [--log-interval S]
                          [--restart] [--dry-run] [--list]
                          [--config FILE] [--ignore-schedule] [--no-path-index]
  neofinder-stub-export.py install [--config FILE] [--interval S] [--dry-run]
  neofinder-stub-export.py remove | enable | disable [--dry-run]
  neofinder-stub-export.py pause
  neofinder-stub-export.py resume | restart [--config FILE] [--now]
  neofinder-stub-export.py status [--config FILE]
  neofinder-stub-export.py list

  export     the run (default when no subcommand is given)
  install    render the LaunchAgent plist from
             macos/neofinder/neofinder-stub-export.plist.template and bootstrap it
             (requires [schedule] in the config, or --interval SECONDS)
  remove     boot out and delete the LaunchAgent
  enable/disable  set/clear the persistent launchd disable flag
  pause      write control=pause and SIGTERM the running export (it finishes
             the current page, saves state and exits 0 "paused"); while
             control=pause every later export, the nightly agent's too, is
             held at once until `resume`
  resume/restart  control=run, then kickstart the agent; with no agent
             installed it only clears the pause flag and says how to continue,
             unless --now, which starts a foreground export (Ctrl-C pauses it)
  status     installed/enabled/running/paused/schedule/per-catalogue progress
  list       catalogue table (name, volume, items, mounted/offline)

Needs Python >= 3.11 (tomllib); PyObjC (pyobjc-framework-Cocoa) for aliases,
without it every file is a stub (header O). Nothing but stubs and aliases
is ever written under --dest; state, the path index and run.pid live under
~/Library/Application Support/neofinder-stub-export/, logs under
~/Library/Logs/neofinder-stub-export/.

Known limits / decisions (facts measured on this machine, 2026-10-09,
NeoFinder 9.3.1; companion script macos/neofinder/neofinder-spotlight-batch.sh):

  A. `Catalog Items of Catalogue X` is the WHOLE tree, recursively,
     depth-first, folders immediately before their children (verified:
     count 461,153 = 424,913 files + 36,240 folders for mac256usb).
  B. Reading a whole catalogue in one Apple Event fails (error -1741);
     ranged reads `Catalog Items lo thru hi` work. Pages are clipped to the
     item count (a range END past the count fails with -1719 "Invalid index").
     Every `tell application "NeoFinder"` runs inside `with timeout of 600
     seconds` (the AppleScript default of 120 s is too short for a cold
     NeoFinder loading a 5.6 M-item catalogue).
  C. Page costs: one Apple Event per page, each property list joined into
     ONE text column (text item delimiters 0x1F, columns joined with 0x1E);
     the per-record AppleScript concat loop costs 50-75 s more per page and
     is only the fallback. Warm NeoFinder, measured 2026-10-09: ~2.5-3 s per
     10,000-item {kind, size, Modification Date, complete path} page
     (6-8 s before the date loop moved to script-object properties, which
     made the loop O(1) per item), ~2,500 items/s end to end including
     writing in the foreground. Of a page, NeoFinder's own answer is ~1.5-2.3 s
     and the stub writes ~1.4 s. A cold 50,000-item page once took 458 s, and
     page size no longer matters after the loop fix, so the default stays
     10,000. The LaunchAgent runs ProcessType Standard: Background clamps the
     job to background QoS, measured 5-12x slower (perf slice, 2026-10-09).
  D. Dates: AppleScript dates are zone-less WALL-CLOCK values (`b - a`
     across the 2026-03-08 spring-forward hour gives 7200 for one real
     hour). So each date d is returned as wall seconds w = (d - refD) +
     946684800, refD being 2000-01-01 00:00 built inside the script (no
     clock sampling, no jitter); Python turns w into an epoch with
     time.mktime(time.gmtime(w)[:8] + (-1,)), which applies the local DST
     rule of THAT date (ambiguous only in the repeated autumn hour). The
     same w of `last updated`, as y-m-dTh:m:s text, is the clock-free key
     that says whether a catalogue changed since the saved state and the
     path index; its epoch is for display only. A system time-zone change
     shifts every wall value and so counts as "catalogue updated". osascript
     appends one trailing newline to stdout; osa() strips it.
  E. `complete path` is HFS-style: "mac256usb:.AppInstallationStaging". The
     stub path drops the first component (the volume name; the CATALOGUE NAME
     takes its place) and maps any "/" inside a component to ":" (that is how
     macOS stores a "/" in a name at the POSIX level). kind == "Folder" marks
     folders. `name` is never fetched; it is the last path component.
  F. Free-space headroom is checked with os.statvfs against ~2 KB per
     remaining item and warned about in the log (never fatal).
  G. osascript error -1743 means the macOS Automation permission was denied
     (System Settings > Privacy & Security > Automation, terminal app ->
     NeoFinder); the error carries that hint. It is retried like any other
     failing page (cheap) and then ends the run. A launchd run uses the
     python binary's own Automation consent: do its first run by
     `launchctl kickstart` while at the keyboard.
  H. A failing page is retried twice with the page size halved (min 500);
     after that the run exits 1 with a "resume with:" hint. A TRANSPORT
     failure (ragged columns, a stray 0x1E/0x1F in a name) is bisected down
     to single items instead; an item that still fails is skipped, logged
     and flagged x in the path index. A stub that cannot be written
     (ENAMETOOLONG, a file where a folder should be, ...) is skipped and
     logged; only ENOSPC, EROFS, EDQUOT, or EACCES/ENOENT on the catalogue
     directory itself end the run. The summary counts skips and lists the
     first 20. SIGINT aborts mid-page (the half-written page is NOT marked
     done; re-writing stubs is idempotent), no retry follows, exit 130.
     SIGTERM or control=pause finishes the page, saves state and exits 0
     "paused"; the schedule stop time acts like pause. control=pause also
     holds every later run (that is how to hold the nightly agent) until
     the resume subcommand.
  I. The path index pass ({kind, complete path} pages over the catalogue,
     cached in Application Support keyed by the `last updated` key of D, the
     item count and the skip list) makes ETA exact, enables first/refresh
     prefixes and status progress. Measured 2026-10-09: ~8,000 items/s
     (mac256usb ~1 min, Macintosh HD ~12 min); --limit bounds it; it honours
     pause, SIGINT and the schedule stop. --no-path-index skips it (then
     first/refresh are refused).
  J. launchd: per-user LaunchAgent (AppleScript needs the GUI session); no
     sudo anywhere. ProgramArguments start with `/usr/bin/caffeinate -i` so
     an idle Mac does not sleep mid-run (caffeinate forwards SIGTERM to the
     exporter and waits for it, verified 2026-10-09); ExitTimeOut 300 gives
     the exporter time to finish its page on bootout or `kickstart -k`. The
     plist names the stable /opt/homebrew/bin/python3.X link, not the
     versioned Cellar path that `brew cleanup` deletes.
  K. State is keyed by dest: state/<sha1(dest)[:8]>/<catalogue>.json plus
     the folder-mtime journal beside it, with the dest inside the JSON, so a
     test run into $TMPDIR never touches the progress of the real staging
     volume. The path index stays per catalogue (it describes NeoFinder,
     not a dest). A corrupt state JSON is renamed aside (.corrupt-<ts>) and
     the run starts fresh; state is fsynced before it replaces the old file.
  L. Skip list: root-level .Spotlight-V100, .fseventsd, .Trashes,
     .DocumentRevisions-V100 and .TemporaryItems are not exported by default
     (mac256usb items 4-195,370, 42 % of the catalogue, are its Spotlight
     store, measured 2026-10-09). Skipped items are flagged x in the path
     index (indices stay aligned) and never fetched. `skip = [...]` in the TOML (global, or per [[catalog]]) replaces
     the list; entries are prefixes relative to the catalogue root.
  M. refresh prefixes are re-exported every run. After a COMPLETE run (never
     under --limit, where the keep-set would be partial) stubs under a
     refresh prefix whose path is no longer in the catalogue are deleted,
     then folder mtimes are applied. A first/refresh prefix that matches no
     item is warned about.
  N. Refused dests: /, the system volume, $HOME, /Volumes, and any
     directory on the mounted volume of a catalogue being exported (st_dev
     compare; for the boot catalogue that includes the Data volume, so its
     stubs would not end up catalogued by NeoFinder's next rescan).
  O. Aliases (measured on macOS 27, 2026-10-10). The real file of an item
     is <mount point>/<rel> (rel as in E; mount point from
     catalogue_mount_points: /Volumes/<volume name>, or / for the boot
     catalogue, whose /Users etc. reach the Data volume via firmlinks). When
     that lstat()s as a regular file, the item becomes a Finder alias
     (bookmark file, NSURL writeBookmarkData) written to a temp name and
     renamed over the target (an old stub or alias); it gets the real
     file's creation and modification dates (setResourceValues) and Date
     Added (setattrlist ATTR_CMN_ADDEDTIME, unprivileged), and
     com.apple.metadata:kMDItemKind = the real file's localized type
     description (else the catalogued kind). Spotlight finds aliases by
     name and dates and honours that kMDItemKind xattr; it IGNORES
     kMDItemContentType(Tree) and kMDItemLogicalSize xattrs on aliases, so
     none are written (size lives in the Finder comment). A missing real
     file (volume offline, moved, deleted) gets the empty stub, plus the
     kMDItemKind xattr from the catalogued kind; an existing file there
     is kept (never truncated). PyObjC not importable: one warning with the
     install command, stubs for the whole run. Done ranges are not
     revisited, so stubs written before aliases existed stay stubs until a
     full re-export: `export --restart [--catalog NAME]` with the volume
     mounted (it clears the dest's saved state and rewrites every item).
     Cost: ~1.2 ms per alias against ~0.16 ms per stub (2,000 mac256usb
     files, warm), so a 10,000-file page spends ~12 s writing, not ~1.6 s.

  P. Kind tags (tested 2026-10-10, alias-test3). Spotlight ignores content-
     type xattrs on aliases, so `kind:pdf` can never match one; it honours
     _kMDItemUserTags (`tag:nf-pdf`, Finder Tags filter; plain names, no
     colour suffix) and kMDItemKeywords (`kMDItemKeywords == "pdf"`, plain
     words). Every alias and stub therefore gets tag nf-<group> and
     keywords [nf-<group>, <group>] from kind_group(name, kind): the file
     extension via KIND_GROUPS, else words in the Kind string, else no tag.
     `retag PATH [--dry-run]` applies this to an existing batch volume
     (name + stored kMDItemKind), without a re-export.

  Q. More tags (2026-10-10). Spotlight queries an alias's size as the
     ~1 KB bookmark, so every non-folder entry also gets cumulative size
     tags (nf-over1mb, nf-over10mb, nf-over100mb, nf-over1gb, nf-over10gb;
     decimal units as Finder shows them: one tag answers "at least this
     big"), a stub gets nf-offline (its real file was not mounted at
     export time, so it will not open), and an alias carries the real
     file's own Finder tags (_kMDItemUserTags, colour suffix kept). The nf
     tags go into kMDItemKeywords too. `retag` applies all of it: size from
     the Finder comment, offline = zero-byte stub, real tags read through
     the alias's bookmark path (when the real file is unreadable, the
     alias's existing non-nf tags are kept).
  R. Size number, last opened, stub dates, nightly (2026-10-10,
     alias-test4). Every entry also gets its real size as a number in a
     custom attribute, kMDItemNFRealSize (mdfind and saved searches:
     `kMDItemNFRealSize > 2500000000`; Finder's search panel cannot offer
     it). An alias gets the real file's last-opened date (the raw
     com.apple.lastuseddate#PS xattr, which Spotlight reads as
     kMDItemLastUsedDate). Opening through an alias updates only the real
     file, so `retag` re-copies it. Finder's Recents can never list an
     alias (its query wants a public.content type tree); the "NF Recents"
     saved search stands in. A stub's creation and added dates are its
     export time: `stub-dates PATH` asks NeoFinder for each stub's Creation
     Date (by its path-index item number, checked against the complete path
     in the Finder comment), sets both, and marks the stub
     (com.djbclark.nf-crtime) so it is asked once; it asks nothing while
     NeoFinder is not running. `nightly` attaches the batch image unless it
     is mounted, runs retag then stub-dates until --stop-by, and detaches
     only what it attached (Jobber job neofinder-nightly, 01:15-05:45).
     With --index (2026-10-10) the volume stays attached AND indexed until
     the next run: indexing goes off before the passes, the passes stop 15
     minutes before --stop-by, then the root-owned
     /usr/local/libexec/neofinder-spotlight-index (sudo NOPASSWD, installed
     by `just setup` in macos/neofinder/) turns it on and imports. The image
     is attached without -nobrowse in this mode (Spotlight may skip
     nobrowse mounts). If the applier is missing or fails, it detaches what
     it attached, as without --index.

History:
  - 2026-10-09: written (multi-agent batch slice; lead integrates, tests and
    commits). Companion files: neofinder-stub-export.example.toml,
    neofinder-stub-export.plist.template.
  - 2026-10-09 (evening): after review (22 findings): DST-correct mtimes and
    a clock-free `last updated` key, per-item skip on write errors,
    transport bisection, clipped progress ranges, dest-keyed state, skip
    list, caffeinate + ExitTimeOut + stable python in the LaunchAgent,
    AppleEvent timeouts, pid checks, logged error exits, CLI fixes.
  - 2026-10-09 (night): `resume`/`restart` with no agent installed only
    clears the pause flag and prints how to continue; `--now` opts into the
    foreground export (operator's choice: a one-word command should not start
    a long run). First real run: mac256usb, 265,780 stubs in 2m 58s.
    Perf slice (measured, see fact C): AppleScript date loop over
    script-object properties (1.7-1.9x end to end, identical output);
    LaunchAgent ProcessType Standard + LowPriorityIO (5x for scheduled runs);
    the per-item fallback page script got the same script-object loop
    (2,000 items: 1.04 s -> 0.56 s, byte-identical output).
    Not taken yet: prefetching the next page in a thread (1.1-1.2x more),
    rebuilding paths from the index instead of fetching them, reading the
    .neofinder7 file directly.
  - 2026-10-10: Finder aliases instead of stubs for files whose real file
    is on a mounted volume, with real dates and kMDItemKind (header O;
    operator's design). Aliases and stubs are counted separately in page
    log lines and the summary. Old stubs convert on `export --restart`.
  - 2026-10-10 (later): kind tags and keywords (header P) and `retag`.
  - 2026-10-10 (evening): size/offline/real tags (Q); real size number,
    last opened, `stub-dates` and `nightly` (R).
"""

import sys

if sys.version_info < (3, 11):
    print(
        f"neofinder-stub-export.py: needs Python >= 3.11 (found "
        f"{sys.version.split()[0]}); use /opt/homebrew/bin/python3.12 "
        "(or any python3 >= 3.11)",
        file=sys.stderr,
    )
    sys.exit(2)

import argparse
import ctypes
import dataclasses
import datetime as dt
import errno
import hashlib
import json
import os
import plistlib
import re
import signal
import stat
import subprocess
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import tomllib

SCRIPT_NAME = "neofinder-stub-export.py"
LABEL = "com.djbclark.neofinder-stub-export"
DEST_DEFAULT = "/Volumes/NeoFinderBatch"
PAGE_DEFAULT = 10000
PAGE_MIN = 500
LOG_INTERVAL_DEFAULT = 300
CONFIG_DEFAULT = "~/.config/neofinder-stub-export.toml"
LOG_DIR = Path("~/Library/Logs/neofinder-stub-export").expanduser()
CTRL_DIR = Path("~/Library/Application Support/neofinder-stub-export").expanduser()
PLIST_TEMPLATE = "neofinder-stub-export.plist.template"
RS = "\x1e"  # record separator between transport records / columns
US = "\x1f"  # unit separator between fields / column items
FINDER_COMMENT_XATTR = "com.apple.metadata:kMDItemFinderComment"
KIND_XATTR = "com.apple.metadata:kMDItemKind"  # honoured on aliases (header O)
BOOKMARK_FILE_OPT = 1 << 10  # NSURLBookmarkCreationSuitableForBookmarkFile
ATTR_BIT_MAP_COUNT = 5
ATTR_CMN_ADDEDTIME = 0x10000000
ATTR_CMN_CRTIME = 0x00000200
FSOPT_NOFOLLOW = 0x1
ALIAS_TMP_PREFIX = ".nfx-alias-"  # temp name beside the target, then rename
BYTES_PER_ITEM_HEADROOM = 2048
OSA_TIMEOUT = 900  # seconds; the slowest measured 10k page is well under 60 s
AE_TIMEOUT = 600  # AppleEvent `with timeout` (AppleScript's default is 120 s)
WALL_REF_EPOCH = 946684800  # 2000-01-01 00:00 as if UTC; refD in the scripts
SKIP_DEFAULT = [
    ".Spotlight-V100",
    ".fseventsd",
    ".Trashes",
    ".DocumentRevisions-V100",
    ".TemporaryItems",
]

# Kind groups (header P): extension -> group, built from this table. Primary
# classifier of kind_group(); the Kind string's words are the fallback.
# A group's tag is nf-<group>. First listing wins an extension named twice
# (checked by the table build below).
USER_TAGS_XATTR = "com.apple.metadata:_kMDItemUserTags"
KEYWORDS_XATTR = "com.apple.metadata:kMDItemKeywords"
# Size tags (header Q): cumulative, decimal like Finder.
SIZE_TAGS = (
    (1_000_000, "nf-over1mb"),
    (10_000_000, "nf-over10mb"),
    (100_000_000, "nf-over100mb"),
    (1_000_000_000, "nf-over1gb"),
    (10_000_000_000, "nf-over10gb"),
)
OFFLINE_TAG = "nf-offline"
COMMENT_SIZE_RE = re.compile(r" \| (\d+) bytes \| ")
COMMENT_PATH_RE = re.compile(r"^NeoFinder: (.*) \| \d+ bytes \| ")
REAL_SIZE_XATTR = "com.apple.metadata:kMDItemNFRealSize"  # custom (header R)
LASTUSED_XATTR = "com.apple.lastuseddate#PS"  # raw; kMDItemLastUsedDate
STUB_CRTIME_XATTR = "com.djbclark.nf-crtime"  # stub dates came from NeoFinder
NIGHTLY_IMAGE = "~/nfbatch.sparseimage"
NIGHTLY_MOUNT = "/Volumes/NeoFinderBatch"
STUB_DATES_CHUNK = 200  # items per Apple Event script in stub-dates
INDEX_APPLIER = "/usr/local/libexec/neofinder-spotlight-index"
INDEX_MARGIN_S = 900  # nightly --index: passes stop this long before --stop-by
KIND_GROUP_EXTS = {
    "image": "jpg jpeg jpe png gif bmp tif tiff webp heic heif avif svg psd psb "
    "ico icns xcf ai eps jp2 jxl tga exr hdr pict pnt cr2 cr3 crw nef nrw arw "
    "srf sr2 dng raf orf rw2 pef srw x3f 3fr erf kdc mrw dcr raw",
    "movie": "mov mp4 m4v mkv avi wmv flv webm mpg mpeg m2v m2ts mts vob 3gp 3g2 "
    "ogv rm rmvb asf divx f4v mxf braw r3d",
    "audio": "mp3 m4a m4b aac wav aif aiff aifc flac ogg oga opus wma ape wv mka "
    "caf amr au mid midi kar ac3 dts aax alac",
    "pdf": "pdf ps",
    "doc": "doc docx docm dot dotx rtf rtfd pages odt ott wpd wps abw tex",
    "sheet": "xls xlsx xlsm xlsb xlt xltx numbers ods csv tsv",
    "slides": "key keynote ppt pptx pptm pps ppsx pot potx odp",
    "text": "txt text md markdown mdown rst log org asc nfo adoc textile",
    "code": "py pyw sh bash zsh fish js mjs cjs jsx ts tsx swift c h cc cpp cxx hpp "
    "hh m mm go rs java kt kts rb pl pm php lua el lisp clj scala hs ml cs fs vb "
    "r jl dart zig nim ps1 bat cmd awk sed tcl vim applescript scpt "
    "html htm xhtml css scss sass less json5 vue svelte gradle make mk cmake "
    "asm s v sv vhd ino",
    "data": "json xml yaml yml toml plist ini cfg conf sql sqlite sqlite3 db mdb "
    "accdb ndjson jsonl parquet avro arrow feather hdf5 h5 npy npz pkl pickle "
    "mat sav dta xsd dtd rdf ttl proto",
    "archive": "zip gz tgz bz2 tbz tbz2 xz txz 7z rar tar zst tzst lz4 lz lzma z "
    "cab arj sit sitx cpio ar xar jar war whl egg",
    "diskimage": "dmg iso sparseimage sparsebundle img vmdk qcow qcow2 vdi vhdx "
    "cdr toast udif dsk",
    "app": "app pkg mpkg exe msi apk ipa xpi deb rpm appx dll",
    "font": "ttf otf ttc otc woff woff2 eot pfb pfm dfont fon",
    "ebook": "epub mobi azw azw3 azw4 kfx cbz cbr cb7 cbt djvu fb2 lit",
    "email": "eml emlx mbox mbx msg olk14msg pst ost",
}
KIND_GROUPS = {}
for _group, _exts in KIND_GROUP_EXTS.items():
    for _ext in _exts.split():
        KIND_GROUPS.setdefault(_ext, _group)
KIND_GROUP_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz4")
# Fallback: case-insensitive words of the Kind string, first match wins
# (specific before general: "Disk Image" before "Image", PDF first).
KIND_GROUP_WORDS = (
    ("pdf", r"pdf"),
    ("diskimage", r"disk images?|disc images?"),
    ("archive", r"archives?|zip|compressed"),
    ("sheet", r"spreadsheets?|worksheets?|excel|numbers"),
    ("slides", r"presentations?|slideshows?|keynote|powerpoint"),
    ("font", r"fonts?|typefaces?"),
    ("email", r"e-?mail|mailbox"),
    ("ebook", r"e-?books?"),
    ("app", r"applications?|installers?"),
    ("movie", r"movies?|videos?|film"),
    ("audio", r"audio|sound|music|songs?"),
    ("image", r"images?|pictures?|photos?|graphics?"),
    ("code", r"source|scripts?|code|shell"),
    ("doc", r"word|rich text|pages"),
    ("text", r"text|markdown"),
    # Not the bare "Document": macOS names every unknown type that, and it
    # was 15,246 of 15,322 nf-doc files on the batch volume (2026-10-10).
    ("doc", r"(?<=\w\s)documents?"),
)
KIND_GROUP_WORD_RES = tuple(
    (g, re.compile(rf"\b(?:{w})\b", re.I)) for g, w in KIND_GROUP_WORDS
)

FATAL_ERRNOS = {errno.ENOSPC, errno.EROFS, errno.EDQUOT}
SKIP_LIST_SHOWN = 20
DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_stop_now = False  # SIGINT: abort mid-page, exit 130
_pause = False  # SIGTERM / control file / schedule stop: finish page, exit 0


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------


def eprint(*args):
    print(*args, file=sys.stderr)


def now_iso():
    # Local wall-clock timestamps in the log (the schedule is local too).
    return dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def parse_num(s):
    """Parse an AppleScript-rendered number: int, "1.79E+9" real, or junk."""
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return round(float(s))
    except (ValueError, OverflowError):
        return None


def hfs_to_rel(complete_path):
    """'mac256usb:a:b' -> 'a/b' ('/' inside a component becomes ':').

    Returns '' for the volume root, None when the path is not HFS-shaped.
    """
    if not complete_path or ":" not in complete_path:
        return None
    comps = complete_path.split(":")
    parts = [c.replace("/", ":") for c in comps[1:]]
    if not parts or parts == [""]:
        return ""
    if any(p == "" for p in parts):
        return None
    return "/".join(parts)


def rel_to_display(rel):
    return rel or "<catalogue root>"


def human_secs(seconds):
    s = max(0, int(seconds))
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m {sec:02d}s" if h else f"{m}m {sec:02d}s"


# --------------------------------------------------------------------------
# AppleScript bridge (read-only queries; never any set/delete/make/...)
# --------------------------------------------------------------------------


class OsaError(RuntimeError):
    pass


def osa(script, timeout=OSA_TIMEOUT):
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OsaError(f"osascript timed out after {timeout} s") from exc
    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "-1743" in err:
            raise OsaError(
                "AUTOMATION_DENIED: Not authorized to send Apple events to "
                "NeoFinder (error -1743). Allow it in System Settings > "
                "Privacy & Security > Automation for this terminal "
                "application, then rerun."
            )
        raise OsaError(f"osascript failed: {err or '<no message>'}")
    # osascript appends exactly one newline to stdout; without stripping it,
    # the last field of the last transport record/column absorbs it.
    return proc.stdout.removesuffix("\n")


class Interrupted(RuntimeError):
    """SIGINT (or a pause inside the path index pass) stopped the work."""


def wall_to_epoch(w):
    """Local wall seconds (wall clock read as if UTC) -> real epoch.

    mktime applies the DST rule of that date (isdst=-1), header D.
    """
    try:
        return int(time.mktime(time.gmtime(w)[:8] + (-1,)))
    except (OverflowError, OSError, ValueError):
        return None


def wall_key(w):
    """Clock-free y-m-dTh:m:s text of a wall-seconds value (header D)."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(w))
    except (OverflowError, OSError, ValueError):
        return None


@dataclasses.dataclass
class Catalogue:
    name: str
    volume: str | None
    files: int
    folders: int
    last_updated: int | None  # epoch, display only
    lu_key: str | None = None  # wall-clock text: the change key (header D)

    @property
    def total(self):
        return self.files + self.folders


def asa_quote(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


# refD = 2000-01-01 00:00 local wall time, built without sampling any clock.
# `d - refD` is then a zone-less wall-clock difference (header D). These
# `set ... of r` lines assign to a LOCAL AppleScript date, never to NeoFinder.
WALLREF_HANDLER = """
on wallRef()
	set r to current date
	set day of r to 1
	set year of r to 2000
	set month of r to 1
	set day of r to 1
	set time of r to 0
	return r
end wallRef
"""

CATLIST_SCRIPT = (
    WALLREF_HANDLER
    + """
on txtOf(v)
	try
		if class of v is date then return "DATE"
		return v as text
	on error
		return ""
	end try
end txtOf

on run
	set refD to my wallRef()
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			set {ns, vs, fs, ds, lus} to {name, volume name, file number, folder number, last updated} of Catalogues
		end tell
	end timeout
	set RS to character id 30
	set US to character id 31
	set out to {}
	repeat with i from 1 to count of ns
		set lu to item i of lus
		if class of lu is date then
			set lu2 to (lu - refD) as text
		else
			set lu2 to ""
		end if
		set end of out to (my txtOf(item i of ns)) & US & (my txtOf(item i of vs)) & US & (my txtOf(item i of fs)) & US & (my txtOf(item i of ds)) & US & lu2
	end repeat
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, RS}
	set o to out as text
	set AppleScript's text item delimiters to TID
	return o
end run
"""
).replace("@AET@", str(AE_TIMEOUT))


def fetch_catalogues():
    """Query NeoFinder for every catalogue with its counts and volume."""
    out = osa(CATLIST_SCRIPT)
    cats = []
    for rec in out.split(RS):
        f = rec.split(US)
        if len(f) != 5:
            continue
        rel = parse_num(f[4])
        w = None if rel is None else rel + WALL_REF_EPOCH
        cats.append(
            Catalogue(
                name=f[0],
                volume=f[1] or None,
                files=parse_num(f[2]) or 0,
                folders=parse_num(f[3]) or 0,
                last_updated=None if w is None else wall_to_epoch(w),
                lu_key=None if w is None else wall_key(w),
            )
        )
    if not cats:
        raise OsaError("NeoFinder returned no catalogues")
    return cats


# One Apple Event per page: the multi-property `of Catalog Items lo thru hi`
# form returns a list of per-property lists; each is joined into one text
# column (US between items, RS between columns) so Python gets aligned
# columns without any per-record AppleScript string building (header, C).
# Dates go out as wall seconds since refD (header D); "" = no date.
PAGE_SCRIPT = (
    WALLREF_HANDLER
    + """
on run
	set refD to my wallRef()
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			set {ks, szs, mds, ps} to {kind, size, Modification Date, complete path} of Catalog Items @LO@ thru @HI@ of Catalogue "@CAT@"
		end tell
	end timeout
	set US to character id 31
	set RS to character id 30
	-- Script-object properties make `item i of` and `set end of` O(1);
	-- on plain local lists this loop cost ~3 s per 10,000 items.
	script o
		property ml : mds
		property dl : {}
	end script
	repeat with i from 1 to count of o's ml
		set d to item i of o's ml
		if class of d is date then
			set end of o's dl to (d - refD)
		else
			set end of o's dl to ""
		end if
	end repeat
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, US}
	set c0 to ks as text
	set c1 to szs as text
	set c2 to (o's dl) as text
	set c3 to ps as text
	set AppleScript's text item delimiters to TID
	return c0 & RS & c1 & RS & c2 & RS & c3
end run
"""
)

# Fallback for a page where a bulk join chokes on a missing value: guarded
# per-record conversion (slow, header, C, but robust).
PAGE_SCRIPT_SLOW = (
    WALLREF_HANDLER
    + """
on run
	set refD to my wallRef()
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			set {ks, szs, mds, ps} to {kind, size, Modification Date, complete path} of Catalog Items @LO@ thru @HI@ of Catalogue "@CAT@"
		end tell
	end timeout
	set US to character id 31
	set RS to character id 30
	-- Script-object properties: `item i of` a plain list is O(i), so the
	-- bare loop was O(n^2) per page (same fix as PAGE_SCRIPT, 2026-10-09).
	script sc
		property kl : ks
		property sl : szs
		property ml : mds
		property pl : ps
		property out : {}
	end script
	repeat with i from 1 to count of sc's kl
		try
			set k2 to (item i of sc's kl) as text
		on error
			set k2 to ""
		end try
		try
			set s2 to (item i of sc's sl) as text
		on error
			set s2 to ""
		end try
		set d to item i of sc's ml
		if class of d is date then
			set d2 to ((d - refD) as text)
		else
			set d2 to ""
		end if
		try
			set p2 to (item i of sc's pl) as text
		on error
			set p2 to ""
		end try
		set end of sc's out to k2 & US & s2 & US & d2 & US & p2
	end repeat
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, RS}
	set o to (sc's out) as text
	set AppleScript's text item delimiters to TID
	return o
end run
"""
)


def _page_script(template, cat, lo, hi):
    return (
        template.replace("@LO@", str(lo))
        .replace("@HI@", str(hi))
        .replace("@AET@", str(AE_TIMEOUT))
        .replace("@CAT@", asa_quote(cat))
    )


@dataclasses.dataclass
class ItemRec:
    kind: str
    size: int
    mtime: int | None
    complete_path: str


def _mtime_from(field):
    rel = parse_num(field)
    return None if rel is None else wall_to_epoch(rel + WALL_REF_EPOCH)


def is_transport(exc):
    return str(exc).startswith("transport:")


def parse_columns(out, nfields):
    cols = out.split(RS)
    if len(cols) != nfields:
        raise OsaError(f"transport: expected {nfields} columns, got {len(cols)}")
    rows = [c.split(US) for c in cols]
    n = len(rows[0])
    if any(len(r) != n for r in rows):
        raise OsaError(f"transport: ragged columns ({[len(r) for r in rows]})")
    return rows, n


def _records_from_slow(out, want):
    """Parse the per-record fallback transport (RS between records)."""
    recs = []
    for r in out.split(RS):
        f = r.split(US)
        if len(f) != 4:
            raise OsaError(f"transport: record with {len(f)} fields, wanted 4")
        recs.append(
            ItemRec(
                kind=f[0],
                size=parse_num(f[1]) or 0,
                mtime=_mtime_from(f[2]),
                complete_path=f[3],
            )
        )
    if len(recs) != want:
        raise OsaError(f"transport: {len(recs)} records, wanted {want}")
    return recs


def fetch_items_page(cat, lo, hi):
    """One page of {kind, size, Modification Date, complete path}."""
    want = hi - lo + 1
    try:
        rows, n = parse_columns(osa(_page_script(PAGE_SCRIPT, cat, lo, hi)), 4)
    except OsaError as exc:
        if "into type" in str(exc) or "missing value" in str(exc):
            return _records_from_slow(
                osa(_page_script(PAGE_SCRIPT_SLOW, cat, lo, hi)), want
            )
        raise
    recs = []
    for i in range(n):
        recs.append(
            ItemRec(
                kind=rows[0][i],
                size=parse_num(rows[1][i]) or 0,
                mtime=_mtime_from(rows[2][i]),
                complete_path=rows[3][i],
            )
        )
    if len(recs) != want:
        raise OsaError(f"transport: {len(recs)} records, wanted {want}")
    return recs


PATHS_SCRIPT = """
on run
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			set {ks, ps} to {kind, complete path} of Catalog Items @LO@ thru @HI@ of Catalogue "@CAT@"
		end tell
	end timeout
	set US to character id 31
	set RS to character id 30
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, US}
	set c0 to ks as text
	set c1 to ps as text
	set AppleScript's text item delimiters to TID
	return c0 & RS & c1
end run
"""

PATHS_SCRIPT_SLOW = """
on run
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			set {ks, ps} to {kind, complete path} of Catalog Items @LO@ thru @HI@ of Catalogue "@CAT@"
		end tell
	end timeout
	set US to character id 31
	set RS to character id 30
	set out to {}
	repeat with i from 1 to count of ks
		try
			set k2 to (item i of ks) as text
		on error
			set k2 to ""
		end try
		try
			set p2 to (item i of ps) as text
		on error
			set p2 to ""
		end try
		set end of out to k2 & US & p2
	end repeat
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, RS}
	set o to out as text
	set AppleScript's text item delimiters to TID
	return o
end run
"""


def fetch_paths_page(cat, lo, hi):
    """One page of (is_folder, complete path) for the path index pass."""
    want = hi - lo + 1
    try:
        rows, n = parse_columns(osa(_page_script(PATHS_SCRIPT, cat, lo, hi)), 2)
    except OsaError as exc:
        if "into type" in str(exc) or "missing value" in str(exc):
            out = []
            for r in osa(_page_script(PATHS_SCRIPT_SLOW, cat, lo, hi)).split(RS):
                f = r.split(US)
                if len(f) != 2:
                    raise OsaError(
                        f"transport: record with {len(f)} fields, wanted 2"
                    ) from None
                out.append((f[0].strip().lower() == "folder", f[1]))
            if len(out) != want:
                raise OsaError(
                    f"transport: {len(out)} records, wanted {want}"
                ) from None
            return out
        raise
    out = [(rows[0][i].strip().lower() == "folder", rows[1][i]) for i in range(n)]
    if len(out) != want:
        raise OsaError(f"transport: {len(out)} records, wanted {want}")
    return out


def fetch_bisect(fetch, cat, lo, hi, log, bad, what):
    """fetch(cat, lo, hi); on a TRANSPORT mismatch split the range in two,
    down to single items (header H). An item that still fails becomes None
    in the result and its index goes into `bad`. Other errors propagate.
    """
    if _stop_now:
        raise Interrupted("interrupt")
    try:
        return fetch(cat, lo, hi)
    except OsaError as exc:
        if _stop_now:
            raise Interrupted("interrupt") from None
        if not is_transport(exc):
            raise
        if lo == hi:
            log.warning(
                f"{cat}: {what} item {lo} unreadable over the transport "
                f"({exc}); skipped and flagged x"
            )
            bad.append(lo)
            return [None]
        mid = (lo + hi) // 2
        log.warning(f"{cat}: {what} {lo}-{hi}: {exc}; bisecting")
        return fetch_bisect(fetch, cat, lo, mid, log, bad, what) + fetch_bisect(
            fetch, cat, mid + 1, hi, log, bad, what
        )


# --------------------------------------------------------------------------
# config (TOML) and schedule
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Schedule:
    start: int  # minutes since midnight, local
    stop: int
    days: set  # python weekday() numbers, 0 = Monday


@dataclasses.dataclass
class CatalogCfg:
    name: str
    enabled: bool = True
    first: list = dataclasses.field(default_factory=list)
    refresh: list = dataclasses.field(default_factory=list)
    skip: list | None = None  # None = the global list


@dataclasses.dataclass
class Config:
    dest: str = DEST_DEFAULT
    page: int = PAGE_DEFAULT
    log_interval: int = LOG_INTERVAL_DEFAULT
    schedule: Schedule | None = None
    catalogs: list = dataclasses.field(default_factory=list)  # CatalogCfg
    skip: list = dataclasses.field(default_factory=lambda: list(SKIP_DEFAULT))

    def skip_for(self, ccfg):
        return ccfg.skip if ccfg is not None and ccfg.skip is not None else self.skip


def _prefix_list(values, where):
    """Config prefixes: strings relative to the catalogue root, no edge '/'."""
    if not isinstance(values, list):
        raise SystemExit(f"config {where} must be a list of strings")
    out = []
    for v in values:
        p = str(v).strip().strip("/")
        if p:
            out.append(p)
    return out


def _parse_hhmm(s):
    try:
        h, m = s.strip().split(":")
        hh, mm = int(h), int(m)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError
        return hh * 60 + mm
    except ValueError:
        raise ValueError(f"bad HH:MM time: {s!r}") from None


def load_config(path):
    cfg = Config()
    p = Path(path).expanduser()
    if not p.exists():
        # The default may be absent; an explicit path (even the default
        # written out in full, as launchd and `resume` pass it) must exist.
        if p != Path(CONFIG_DEFAULT).expanduser():
            eprint(f"Error: config file not found: {p}")
            raise SystemExit(2)
        return cfg, p
    with open(p, "rb") as fh:
        data = tomllib.load(fh)
    for key in data:
        if key not in ("dest", "page", "log_interval", "schedule", "catalog", "skip"):
            eprint(f"warning: unknown config key {key!r} in {p}")
    if "skip" in data:
        cfg.skip = _prefix_list(data["skip"], "skip")
    if isinstance(data.get("dest"), str):
        cfg.dest = data["dest"]
    if isinstance(data.get("page"), int):
        cfg.page = max(PAGE_MIN, data["page"])
    if isinstance(data.get("log_interval"), int):
        cfg.log_interval = max(5, data["log_interval"])
    sch = data.get("schedule")
    if sch is not None:
        try:
            start = _parse_hhmm(str(sch["start"]))
            stop = _parse_hhmm(str(sch["stop"]))
        except KeyError as exc:
            raise SystemExit(
                f"config [schedule] needs 'start' and 'stop' (missing {exc})"
            ) from None
        if start == stop:
            raise SystemExit("config [schedule]: start == stop is ambiguous")
        days = sch.get("days") or list(DAY_NAMES)
        try:
            dayset = {DAY_NAMES[str(d).lower()[:3]] for d in days}
        except KeyError:
            raise SystemExit(f"config [schedule]: bad days list {days!r}") from None
        cfg.schedule = Schedule(start, stop, dayset)
    for c in data.get("catalog", []):
        if not isinstance(c, dict) or "name" not in c:
            raise SystemExit(f"config [[catalog]] entry without a name: {c}")
        cfg.catalogs.append(
            CatalogCfg(
                name=str(c["name"]),
                enabled=bool(c.get("enabled", True)),
                first=_prefix_list(c.get("first", []), "[[catalog]] first"),
                refresh=_prefix_list(c.get("refresh", []), "[[catalog]] refresh"),
                skip=(
                    _prefix_list(c["skip"], "[[catalog]] skip") if "skip" in c else None
                ),
            )
        )
    return cfg, p


# Schedule maths uses NAIVE local datetimes (local_now()): replace() and
# timedelta then move along the wall clock, so 06:30 stays 06:30 on the two
# DST-change nights (an aware now() carries a fixed UTC offset).
def local_now():
    return dt.datetime.now().astimezone().replace(tzinfo=None)


def _next_occurrence(now, minutes):
    cand = now.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
    if cand <= now:
        cand += dt.timedelta(days=1)
    return cand


def in_window(now, sched):
    """(inside, stop_deadline). No schedule = always inside, no deadline."""
    if sched is None:
        return True, None
    nm = now.hour * 60 + now.minute
    wd = now.weekday()
    if sched.start < sched.stop:  # same-day window
        inside = sched.start <= nm < sched.stop and wd in sched.days
    else:  # crosses midnight: evening part today, morning part tomorrow
        yesterday = (wd - 1) % 7
        inside = (nm >= sched.start and wd in sched.days) or (
            nm < sched.stop and yesterday in sched.days
        )
    if not inside:
        return False, None
    return True, _next_occurrence(now, sched.stop)


def next_window_start(now, sched):
    if sched is None:
        return None
    for offset in range(8):
        day = now + dt.timedelta(days=offset)
        if day.weekday() not in sched.days:
            continue
        cand = day.replace(
            hour=sched.start // 60, minute=sched.start % 60, second=0, microsecond=0
        )
        if cand > now:
            return cand
    return None


def describe_schedule(sched):
    if sched is None:
        return "none (runs whenever started)"
    days = "/".join(
        n for n, i in sorted(DAY_NAMES.items(), key=lambda kv: kv[1]) if i in sched.days
    )
    return (
        f"{sched.start // 60:02d}:{sched.start % 60:02d}-"
        f"{sched.stop // 60:02d}:{sched.stop % 60:02d} {days}"
    )


# --------------------------------------------------------------------------
# logging and progress
# --------------------------------------------------------------------------


class RunLog:
    def __init__(self, path=None, enabled=True):
        self.enabled = enabled
        self.fh = None
        self.last_beat = 0.0
        if not enabled:
            return
        if path:
            self.path = Path(path).expanduser()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        else:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            self.path = LOG_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.log"
            self.fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
            latest = LOG_DIR / "latest.log"
            try:
                if latest.is_symlink() or latest.exists():
                    latest.unlink()
                latest.symlink_to(self.path.name)
            except OSError:
                pass
        self.line(f"{SCRIPT_NAME} started, pid {os.getpid()}")

    def line(self, msg, prefix=""):
        if not self.enabled or self.fh is None:
            return
        stamp = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
        self.fh.write(f"{stamp} {prefix}{msg}\n")
        self.fh.flush()

    def info(self, msg):
        self.line(msg)

    def warning(self, msg):
        self.line(msg, prefix="WARNING: ")

    def error(self, msg):
        self.line(msg, prefix="ERROR: ")

    def heartbeat(self, msg, force=False, interval=LOG_INTERVAL_DEFAULT):
        now = time.monotonic()
        if force or now - self.last_beat >= interval:
            self.last_beat = now
            self.line(msg)

    def close(self):
        if self.fh:
            self.fh.close()
            self.fh = None


def subcmd_log(msg):
    """One-line log for the launchd/control subcommands."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "subcommands.log", "a", encoding="utf-8") as fh:
        stamp = dt.datetime.now().astimezone().replace(microsecond=0).isoformat()
        fh.write(f"{stamp} {msg}\n")


class Progress:
    def __init__(self, enabled):
        self.enabled = enabled
        self.tty = enabled and sys.stderr.isatty()
        self.samples = []  # (monotonic_t, cumulative)
        self.t0 = time.monotonic()

    def line(self, cat, done, total, extra=""):
        if not self.enabled:
            return
        now = time.monotonic()
        self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[0][0] > 120:
            self.samples.pop(0)
        elapsed = now - self.t0
        pct = (100.0 * done / total) if total else 0.0
        rate_txt, eta = "warming up", "-"
        if len(self.samples) >= 2:
            (t0, d0), (t1, d1) = self.samples[0], self.samples[-1]
            if t1 > t0 and d1 > d0:
                rate = (d1 - d0) / (t1 - t0)
                rate_txt = f"{rate:.1f}/s"
                eta = human_secs(max(0, total - done) / rate)
        text = (
            f"[{cat}] {done}/{total} items ({pct:.1f}%) "
            f"{rate_txt} elapsed {human_secs(elapsed)} ETA {eta}"
            f"{' ' + extra if extra else ''}"
        )
        if self.tty:
            eprint("\r" + text + " " * 8)
        else:
            eprint(text)

    def stat_line(self, cat, done, total, base=0):
        """Same numbers as the progress line, for log heartbeats (the rate
        counts only items done in this run: done - base)."""
        elapsed = time.monotonic() - self.t0
        rate = (done - base) / elapsed if elapsed > 1 else 0.0
        eta = human_secs(max(0, total - done) / rate) if rate > 0 else "-"
        return (
            f"{cat}: {done}/{total} items, {rate:.1f}/s, elapsed "
            f"{human_secs(elapsed)}, ETA {eta}"
        )


# --------------------------------------------------------------------------
# path index (paths/<catalogue>.txt + .meta.json + .off)
# --------------------------------------------------------------------------


def _skip_match(rel, skip):
    return any(rel == p or rel.startswith(p + "/") for p in skip)


class PathsIndex:
    """Line-per-item index: '<d|f|x>' + US + rel path; 1-based item == line.

    'x' marks an item that is never exported: a path that cannot be stored
    (a newline in a name; rel left empty), an item unreadable over the
    transport (header H), or an item under the skip list (header L; rel
    kept). It keeps the line alignment.
    """

    def __init__(self, catalogue):
        self.cat = catalogue.name
        self.txt = CTRL_DIR / "paths" / f"{self.cat}.txt"
        self.meta_path = CTRL_DIR / "paths" / f"{self.cat}.meta.json"
        self.off_path = CTRL_DIR / "paths" / f"{self.cat}.off"
        self.total = 0
        self.lu_key = None
        self.skip_ranges = []
        self._off = None  # cached line offsets (finding 20)

    def valid_for(self, catalogue, top, skip):
        if not self.txt.exists() or not self.meta_path.exists():
            return False
        try:
            meta = json.loads(self.meta_path.read_text())
        except (ValueError, OSError):
            return False
        return (
            meta.get("total", 0) >= top
            and meta.get("lu_key") is not None
            and meta.get("lu_key") == catalogue.lu_key
            and meta.get("skip") == list(skip)
        )

    def load_meta(self):
        meta = json.loads(self.meta_path.read_text())
        self.total = meta["total"]
        self.lu_key = meta.get("lu_key")
        self.skip_ranges = [tuple(r) for r in meta.get("skip_ranges", [])]
        self._off = None

    def build(self, catalogue, top, page, log, progress, stop_check, skip, interval):
        """Fetch {kind, complete path} pages and write the index atomically."""
        self.txt.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.txt.with_suffix(".txt.tmp")
        t0 = time.time()
        log.info(
            f"{self.cat}: building path index for {top} items (page {page}, "
            f"skip {skip})"
        )
        written = 0
        skip_idx = []
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            lo = 1
            while lo <= top:
                stop_check("path index")
                hi = min(lo + page - 1, top, catalogue.total)
                rows = fetch_bisect(
                    fetch_paths_page, self.cat, lo, hi, log, [], "path index"
                )
                buf = []
                for i, row in enumerate(rows):
                    rel = None if row is None else hfs_to_rel(row[1])
                    if rel is None or "\n" in rel or "\r" in rel:
                        flag, rel = "x", ""
                    elif skip and _skip_match(rel, skip):
                        flag = "x"
                        skip_idx.append(lo + i)
                    else:
                        flag = "d" if row[0] else "f"
                    buf.append(flag + US + rel + "\n")
                fh.write("".join(buf))
                written += len(rows)
                progress.line(self.cat, written, top, "path index")
                log.heartbeat(
                    progress.stat_line(self.cat, written, top) + " (path index)",
                    interval=interval,
                )
                lo = hi + 1
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.txt)
        self.skip_ranges = merge_ranges((i, i + 1) for i in skip_idx)
        meta = {
            "total": written,
            "lu_key": catalogue.lu_key,
            "last_updated": catalogue.last_updated,
            "skip": list(skip),
            "skip_ranges": [list(r) for r in self.skip_ranges],
            "volume": catalogue.volume,
            "built": now_iso(),
        }
        write_atomic(self.meta_path, json.dumps(meta, indent=1))
        self.off_path.unlink(missing_ok=True)  # rebuilt lazily
        self._off = None
        self.total = written
        self.lu_key = catalogue.lu_key
        dt_s = max(time.time() - t0, 1e-6)
        log.info(
            f"{self.cat}: path index built: {written} items in "
            f"{human_secs(dt_s)} ({written / dt_s:.1f}/s), "
            f"{covered_len(self.skip_ranges)} under the skip list"
        )

    def _offsets(self):
        """Byte offsets of every line start; cached, rebuilt on demand."""
        import array

        if self._off is not None:
            return self._off
        if self.off_path.exists():
            off = array.array("q")
            with open(self.off_path, "rb") as fh:
                off.frombytes(fh.read())
            if len(off) == self.total + 1:
                self._off = off
                return off
        off = array.array("q", [0])
        with open(self.txt, "rb") as fh:
            pos = 0
            for _ in range(self.total):
                line = fh.readline()
                pos += len(line)
                off.append(pos)
        tmp = self.off_path.with_suffix(".off.tmp")
        with open(tmp, "wb") as fh:
            fh.write(off.tobytes())
        os.replace(tmp, self.off_path)
        self._off = off
        return off

    def get(self, lo, hi):
        """Rows [lo..hi] (1-based inclusive) as [(flag, rel), ...]."""
        off = self._offsets()
        out = []
        with open(self.txt, "rb") as fh:
            fh.seek(off[lo - 1])
            blob = fh.read(off[hi] - off[lo - 1]).decode("utf-8")
        for raw in blob.split("\n")[: hi - lo + 1]:
            if US in raw:
                flag, rel = raw.split(US, 1)
            else:
                flag, rel = "x", ""
            out.append((flag, rel))
        return out

    def mark_x(self, i):
        """Flag item i as never-exported in place (one byte, same length)."""
        off = self._offsets()
        with open(self.txt, "r+b") as fh:
            fh.seek(off[i - 1])
            fh.write(b"x")

    def match_prefixes(self, prefixes, top):
        """{prefix: (lo, hi)} over items 1..top; depth-first order makes a
        prefix's subtree one contiguous range. Unmatched prefixes are absent.
        """
        found = {}
        if not prefixes:
            return found
        with open(self.txt, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh, start=1):
                if i > min(self.total, top):
                    break
                rel = line.rstrip("\n").split(US, 1)[-1]
                for p in prefixes:
                    if rel == p or rel.startswith(p + "/"):
                        if p not in found:
                            found[p] = [i, i + 1]
                        else:
                            found[p][1] = i + 1
        return {p: (r[0], r[1]) for p, r in found.items()}

    def rel_set(self, lo, hi):
        return {rel for flag, rel in self.get(lo, hi - 1) if flag != "x"}


# --------------------------------------------------------------------------
# state (done ranges) and stub writing
# --------------------------------------------------------------------------


def dest_key(dest):
    return hashlib.sha1(str(dest).encode()).hexdigest()[:8]


def state_dir(dest):
    """State is keyed by dest (header K); the path index is not."""
    return CTRL_DIR / "state" / dest_key(dest)


def state_file(cat, dest):
    return state_dir(dest) / f"{cat}.json"


def folders_journal(cat, dest):
    return state_dir(dest) / f"{cat}.folders.tsv"


def write_atomic(path, text):
    """Temp file, fsync, rename: never an empty file after a power loss."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def fresh_state(cat, dest, lu_key=None):
    return {
        "version": 2,
        "catalogue": cat,
        "dest": str(dest),
        "total": 0,
        "done": [],
        "counts": {},
        "finished": False,
        "started": now_iso(),
        "updated": now_iso(),
        "lu_key": lu_key,
    }


def load_state(cat, dest, log):
    p = state_file(cat, dest)
    if not p.exists():
        return fresh_state(cat, dest)
    try:
        st = json.loads(p.read_text())
        problem = (
            None
            if isinstance(st, dict) and isinstance(st.get("done"), list)
            else "not a state object"
        )
    except (ValueError, OSError) as exc:
        st, problem = None, str(exc)
    if problem is None:
        return st
    aside = p.with_name(p.name + f".corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(p, aside)
    except OSError:
        aside = None
    log.warning(
        f"{cat}: state file {p} is unreadable ({problem}); moved aside to "
        f"{aside or '<could not rename>'}; starting fresh"
    )
    return fresh_state(cat, dest)


def save_state(state, dest):
    state["updated"] = now_iso()
    write_atomic(state_file(state["catalogue"], dest), json.dumps(state, indent=1))


def merge_ranges(ranges):
    """Sorted, disjoint, merged list of half-open (lo, hi) ranges."""
    merged = []
    for lo, hi in sorted((int(a), int(b)) for a, b in ranges):
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(lo, hi) for lo, hi in merged]


def clip_ranges(ranges, total):
    """Clip to [1, total + 1) (finding 4: nothing beyond --limit counts)."""
    return merge_ranges((max(lo, 1), min(hi, total + 1)) for lo, hi in ranges)


def subtract_ranges(ranges, minus):
    out = []
    minus = merge_ranges(minus)
    for lo, hi in merge_ranges(ranges):
        cur = lo
        for mlo, mhi in minus:
            if mhi <= cur or mlo >= hi:
                continue
            if mlo > cur:
                out.append((cur, mlo))
            cur = max(cur, mhi)
            if cur >= hi:
                break
        if cur < hi:
            out.append((cur, hi))
    return out


def add_done(state, lo, hi):
    """Merge [lo, hi) into the sorted disjoint done-range list."""
    state["done"] = [list(r) for r in merge_ranges(list(state["done"]) + [(lo, hi)])]


def covered_len(ranges):
    return sum(hi - lo for lo, hi in merge_ranges(ranges))


_LIBC = ctypes.CDLL(None, use_errno=True)
_LIBC.setxattr.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
]


_LIBC.setattrlist.argtypes = [
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
]


class _AttrList(ctypes.Structure):  # <sys/attr.h> struct attrlist
    _fields_ = [
        ("bitmapcount", ctypes.c_ushort),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    ]


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def _set_plist_xattr(path, name, value):
    """Set xattr `name` to a binary plist of `value`.

    Python has no os.setxattr on macOS, hence the libc call.
    """
    blob = plistlib.dumps(value, fmt=plistlib.FMT_BINARY)
    rc = _LIBC.setxattr(os.fsencode(path), name.encode(), blob, len(blob), 0, 0)
    if rc != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path)


def set_finder_comment(path, text_value):
    """Set kMDItemFinderComment (which Spotlight indexes) to the string."""
    _set_plist_xattr(path, FINDER_COMMENT_XATTR, text_value)


def set_kind(path, kind):
    """Set kMDItemKind; Spotlight shows and queries it, alias or stub."""
    if kind:
        _set_plist_xattr(path, KIND_XATTR, kind)


def kind_group(name, kind):
    """Deterministic content group of an item, or None (header P).

    The file extension decides (lower-cased last suffix, `.tar.gz`-style
    compound suffixes are archives); an unknown or missing extension falls
    back to the words of the Kind string; unknown stays None.
    """
    low = (name or "").strip().lower()
    if low.endswith(KIND_GROUP_ARCHIVE_SUFFIXES):
        return "archive"
    ext = os.path.splitext(low)[1][1:]
    group = KIND_GROUPS.get(ext)
    if group is None and kind:
        for g, rx in KIND_GROUP_WORD_RES:
            if rx.search(kind):
                return g
    return group


def nf_tags(group, size, offline):
    """The nf-* tags for an entry: kind group (P), size and offline (Q)."""
    tags = [f"nf-{group}"] if group else []
    tags += [tag for floor, tag in SIZE_TAGS if size >= floor]
    if offline:
        tags.append(OFFLINE_TAG)
    return tags


def set_nf_tags(path, group, size=0, offline=False, user_tags=()):
    """Write Finder tags, keywords and the real size (headers P, Q, R).

    Tags are nf_tags() plus `user_tags` (the real file's own Finder tags,
    written as given); keywords are nf_tags() plus the bare group name.
    Overwrites: these files are ours. Nothing to write writes nothing, and
    a value already there is not rewritten (retag runs nightly).
    """
    nf = nf_tags(group, size, offline)
    tags = nf + [t for t in user_tags if isinstance(t, str) and t not in nf]
    if tags:
        _put_plist_xattr(path, USER_TAGS_XATTR, tags)
    if nf:
        _put_plist_xattr(path, KEYWORDS_XATTR, nf + ([group] if group else []))
    if size > 0:
        _put_plist_xattr(path, REAL_SIZE_XATTR, int(size))


def _put_plist_xattr(path, name, value):
    """_set_plist_xattr unless the xattr already holds `value`."""
    if get_plist_xattr(path, name) != value:
        _set_plist_xattr(path, name, value)


def real_user_tags(path):
    """The Finder tags on the file at `path` (a list), [] when none/unreadable."""
    tags = get_plist_xattr(path, USER_TAGS_XATTR)
    return [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []


def set_added_time(path, epoch):
    """Set the Finder "Date Added" (ATTR_CMN_ADDEDTIME); no root needed."""
    _set_attr_time(path, ATTR_CMN_ADDEDTIME, epoch)


def set_creation_time(path, epoch):
    """Set the creation date (ATTR_CMN_CRTIME); the owner needs no root."""
    _set_attr_time(path, ATTR_CMN_CRTIME, epoch)


def _set_attr_time(path, attr, epoch):
    """setattrlist one common timespec attribute, not following links.

    The setattrlist buffer for a single timespec attribute is just the
    timespec (no length word), as in the reference mkalias.swift (header O).
    """
    al = _AttrList(bitmapcount=ATTR_BIT_MAP_COUNT, commonattr=attr)
    sec = int(epoch // 1)
    ts = _Timespec(sec, int((epoch - sec) * 1e9))
    rc = _LIBC.setattrlist(
        os.fsencode(path),
        ctypes.byref(al),
        ctypes.byref(ts),
        ctypes.sizeof(ts),
        FSOPT_NOFOLLOW,
    )
    if rc != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), path)


# --------------------------------------------------------------------------
# Finder aliases (PyObjC Foundation; optional, header O)
# --------------------------------------------------------------------------

_F = None  # the Foundation module once loaded; False = unavailable this run


def load_foundation(log):
    """Import PyObjC's Foundation once; on failure warn ONCE, stubs only."""
    global _F
    if _F is None:
        try:
            import Foundation  # optional dependency (header O)

            _F = Foundation
        except ImportError as exc:
            _F = False
            msg = (
                f"PyObjC Foundation not importable ({exc}); writing empty stubs "
                f"instead of Finder aliases for this run. Install with: uv pip "
                f"install --python {sys.executable} --break-system-packages "
                f"pyobjc-framework-Cocoa"
            )
            eprint(f"warning: {msg}")
            log.warning(msg)
    return _F or None


class AliasSourceError(RuntimeError):
    """The REAL file could not be bookmarked or read: fall back to a stub."""


def _nserror_oserror(err, path):
    """An NSError from a write under dest -> OSError with the POSIX errno."""
    code = errno.EIO
    try:
        if err.domain() == "NSPOSIXErrorDomain":
            code = int(err.code())
        else:
            under = err.userInfo().get("NSUnderlyingError")
            if under is not None and under.domain() == "NSPOSIXErrorDomain":
                code = int(under.code())
    except (AttributeError, TypeError, ValueError):
        pass
    return OSError(code, os.strerror(code), str(path))


def write_alias(real, target, comment, kind_fallback, size=0):
    """Write a Finder alias to `real` at `target`, replacing what is there.

    The bookmark goes to a temp name in the target's directory, gets the
    Finder comment, kMDItemKind and the real file's creation and
    modification dates, and is renamed over the target (a zero-byte stub
    or an older alias); Date Added is set after the rename. Raises
    AliasSourceError when the real file cannot be bookmarked, OSError for
    write failures under dest.
    """
    F = _F
    src = F.NSURL.fileURLWithPath_(real)
    vals, err = src.resourceValuesForKeys_error_(
        [
            F.NSURLLocalizedTypeDescriptionKey,
            F.NSURLCreationDateKey,
            F.NSURLContentModificationDateKey,
            F.NSURLAddedToDirectoryDateKey,
        ],
        None,
    )
    if vals is None:
        raise AliasSourceError(f"resource values: {err}")
    data, err = (
        src.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
            BOOKMARK_FILE_OPT, None, None, None
        )
    )
    if data is None:
        raise AliasSourceError(f"bookmark: {err}")
    tmp = target.parent / f"{ALIAS_TMP_PREFIX}{os.getpid()}"
    tmp_url = F.NSURL.fileURLWithPath_(str(tmp))
    try:
        ok, err = F.NSURL.writeBookmarkData_toURL_options_error_(
            data, tmp_url, BOOKMARK_FILE_OPT, None
        )
        if not ok:
            raise _nserror_oserror(err, tmp)
        set_finder_comment(tmp, comment)
        kind = (
            str(vals.get(F.NSURLLocalizedTypeDescriptionKey) or "") or kind_fallback
        )
        set_kind(tmp, kind)
        set_nf_tags(
            tmp, kind_group(target.name, kind), size, False, real_user_tags(real)
        )
        copy_last_used(real, tmp)
        dates = {
            k: vals[k]
            for k in (F.NSURLCreationDateKey, F.NSURLContentModificationDateKey)
            if vals.get(k) is not None
        }
        if dates:
            ok, err = tmp_url.setResourceValues_error_(dates, None)
            if not ok:
                raise _nserror_oserror(err, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    added = vals.get(F.NSURLAddedToDirectoryDateKey)
    if added is not None:
        try:
            set_added_time(target, added.timeIntervalSince1970())
        except OSError as exc:  # a dest filesystem without Date Added: keep it
            if exc.errno not in (errno.ENOTSUP, errno.EINVAL):
                raise


def real_regular_file(alias_root, rel):
    """The real file's path when it exists as a regular file, else None."""
    if alias_root is None or not rel:
        return None
    real = os.path.join(alias_root, rel)
    try:
        st = os.lstat(real)
    except (OSError, ValueError):
        return None
    return real if stat.S_ISREG(st.st_mode) else None


class PageCounts:
    def __init__(self):
        self.items = 0
        self.folders = 0
        self.files = 0
        self.aliases = 0  # files written as Finder aliases (subset of files)
        self.stubs = 0  # files written as empty stubs (subset of files)
        self.skipped = 0  # unparseable / unreadable (x) + write failures
        self.failed = 0  # write failures only (subset of skipped)
        self.comments = 0
        self.problems = []  # first SKIP_LIST_SHOWN "index: path (reason)"

    def add(self, other):
        keys = ("items", "folders", "files", "aliases", "stubs", "skipped")
        for k in keys + ("failed", "comments"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        room = SKIP_LIST_SHOWN - len(self.problems)
        if room > 0:
            self.problems += other.problems[:room]

    def note(self, msg):
        if len(self.problems) < SKIP_LIST_SHOWN:
            self.problems.append(msg)


class StubWriteError(RuntimeError):
    """A write failure that ends the run (full, read-only, or cat_dir gone)."""


def _fatal_write_error(exc, cat_dir):
    if exc.errno in FATAL_ERRNOS:
        return True
    if exc.errno in (errno.EACCES, errno.ENOENT):
        return not (cat_dir.is_dir() and os.access(cat_dir, os.W_OK))
    return False


def write_page(
    records, idx_rows, cat_dir, folder_fh, lo, idx, skip, log, alias_root=None
):
    """Write one page of items (lo, lo+1, ...). Returns PageCounts.

    `records` are the fetched items in order (None = unreadable over the
    transport, header H); `idx_rows` the (flag, rel) pairs from the path
    index in the same order (None when no index: the rel path is derived
    from the record's own complete path and `skip` is applied here).
    `alias_root` is where the catalogue's volume is mounted (None: offline,
    or no PyObjC): a file whose <alias_root>/<rel> exists as a regular file
    becomes a Finder alias to it, any other file an empty stub (header O).
    An item that cannot be written is skipped and logged; only the errors of
    _fatal_write_error raise StubWriteError.
    """
    counts = PageCounts()
    if not cat_dir.is_dir():  # never let makedirs recreate a vanished tree
        raise StubWriteError(
            f"catalogue directory {cat_dir} vanished (staging volume unmounted?)"
        )
    for i, rec in enumerate(records):
        if _stop_now:
            raise Interrupted("interrupt")
        n = lo + i
        if rec is None:
            counts.skipped += 1
            counts.note(f"item {n}: unreadable over the transport")
            if idx is not None:
                idx.mark_x(n)
            continue
        if idx_rows is not None:
            flag, rel = idx_rows[i]
            if flag == "x":
                counts.skipped += 1
                if rel == "" and rec.complete_path:
                    counts.note(f"item {n}: unstorable path {rec.complete_path!r}")
                continue
        else:
            rel = hfs_to_rel(rec.complete_path)
            if rel is None or "\n" in rel or "\r" in rel:
                counts.skipped += 1
                counts.note(f"item {n}: unparseable path {rec.complete_path!r}")
                continue
            if skip and _skip_match(rel, skip):
                counts.skipped += 1
                continue
        is_folder = rec.kind.strip().lower() == "folder"
        target = cat_dir if rel == "" else cat_dir / rel
        comment = f"NeoFinder: {rec.complete_path} | {rec.size} bytes | {rec.kind}"
        real = None if is_folder else real_regular_file(alias_root, rel)
        try:
            if is_folder:
                os.makedirs(target, exist_ok=True)
                if folder_fh and rec.mtime is not None:
                    folder_fh.write(f"{rec.mtime}{US}{rel}\n")
                set_finder_comment(target, comment)
            else:
                os.makedirs(target.parent, exist_ok=True)
                if real is not None:
                    try:
                        write_alias(real, target, comment, rec.kind, rec.size)
                    except AliasSourceError as exc:
                        log.warning(f"alias failed, writing a stub: {real} ({exc})")
                        real = None
                if real is None:
                    # Missing real file (volume offline, moved, deleted): the
                    # empty stub. An existing file is kept, not truncated.
                    try:
                        with open(target, "x"):
                            pass
                    except FileExistsError:
                        pass
                    if rec.mtime is not None:
                        os.utime(target, (rec.mtime, rec.mtime))
                    set_finder_comment(target, comment)
                    set_kind(target, rec.kind)
                    set_nf_tags(
                        target, kind_group(target.name, rec.kind), rec.size, True
                    )
        except OSError as exc:
            if _fatal_write_error(exc, cat_dir):
                what = "alias" if real is not None else "stub"
                raise StubWriteError(f"cannot write {what} {target}: {exc}") from None
            counts.skipped += 1
            counts.failed += 1
            code = errno.errorcode.get(exc.errno, str(exc.errno))
            what = "alias" if real is not None else "stub"
            log.warning(f"{what} skipped: {target} ({code}: {exc.strerror})")
            counts.note(f"item {n}: {target} ({code})")
            continue
        counts.items += 1
        counts.comments += 1
        if is_folder:
            counts.folders += 1
        else:
            counts.files += 1
            if real is not None:
                counts.aliases += 1
            else:
                counts.stubs += 1
    return counts


def apply_folder_mtimes(cat, dest, cat_dir, log):
    """Apply deferred folder mtimes (children bump parent mtimes, header)."""
    journal = folders_journal(cat, dest)
    if not journal.exists():
        return 0
    applied = 0
    with open(journal, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or US not in line:
                continue
            mtime_s, rel = line.split(US, 1)
            mtime = parse_num(mtime_s)
            if mtime is None:
                continue
            target = cat_dir if rel == "" else cat_dir / rel
            try:
                os.utime(target, (mtime, mtime))
                applied += 1
            except OSError as exc:
                log.warning(f"folder mtime failed for {target}: {exc}")
    journal.unlink()
    log.info(f"{cat}: applied mtimes to {applied} folders")
    return applied


def remove_stale_stubs(cat_dir, prefix_rel, keep_set, log):
    """Under <cat_dir>/<prefix_rel>, delete stubs/aliases not in keep_set."""
    root = cat_dir / prefix_rel
    if not root.exists():
        return 0
    root_real = str(root.resolve())
    removed = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        d = Path(dirpath)
        for fn in filenames:
            f = d / fn
            rel = f.relative_to(cat_dir).as_posix()
            if rel in keep_set:
                continue
            try:
                if str(f.resolve()).startswith(root_real):
                    f.unlink()
                    removed += 1
            except OSError as exc:
                log.warning(f"could not remove stale stub {f}: {exc}")
        for dn in dirnames:
            sub = d / dn
            rel = sub.relative_to(cat_dir).as_posix()
            if rel in keep_set:
                continue
            try:
                if str(sub.resolve()).startswith(root_real):
                    sub.rmdir()  # only removes when empty
                    removed += 1
            except OSError:
                pass
    if removed:
        log.info(f"removed {removed} stale stub(s) under {prefix_rel}")
    return removed


def check_free_space(dest, remaining_items, cat, log):
    try:
        stv = os.statvfs(dest)
    except OSError:
        return
    free = stv.f_bavail * stv.f_frsize
    need = remaining_items * BYTES_PER_ITEM_HEADROOM
    if free < need:
        log.warning(
            f"{cat}: low space on {dest}: {free / 1e6:.0f} MB free, "
            f"~{need / 1e6:.0f} MB wanted for {remaining_items} remaining "
            f"items (~2 KB each); the staging image may need to be larger"
        )


# --------------------------------------------------------------------------
# export run
# --------------------------------------------------------------------------


def _sigint_handler(signum, frame):
    global _stop_now
    _stop_now = True


def _sigterm_handler(signum, frame):
    global _pause
    _pause = True


def control_says_pause():
    try:
        with open(CTRL_DIR / "control") as fh:
            return fh.read().strip().lower().startswith("pause")
    except OSError:
        return False


def prog_name():
    return sys.argv[0] or SCRIPT_NAME


def resume_hint(dest, catalogs, config_path):
    """The command that continues the run. While control=pause holds every
    export, only the resume subcommand helps (finding 6)."""
    if control_says_pause():
        return f"resume with: {prog_name()} resume"
    parts = [prog_name(), "export", "--dest", str(dest)]
    for c in catalogs:
        parts += ["--catalog", c]
    default_cfg = str(Path(CONFIG_DEFAULT).expanduser())
    if config_path and str(Path(str(config_path)).expanduser()) != default_cfg:
        parts += ["--config", str(config_path)]
    return "resume with: " + " ".join(parts)


def stop_reason_now(schedule_stop):
    """Why the run must stop before the next page, or None."""
    if _stop_now:
        return "interrupt"
    if control_says_pause():
        return "pause"
    if _pause:
        return "sigterm"
    if schedule_stop and local_now() >= schedule_stop:
        return "schedule"
    return None


class StopRun(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def fetch_page_with_retry(cat, lo, hi, page_size, log):
    """Fetch items lo..hi (both INCLUSIVE), retrying with halved sizes.

    Transport mismatches are bisected inside fetch_bisect; other failures
    are retried smaller. Returns (records, hi_done): hi_done is the
    inclusive last index fetched; a record is None when unreadable.
    """
    size = min(page_size, hi - lo + 1)
    attempts = [size]
    while attempts[-1] > PAGE_MIN and len(attempts) < 3:
        attempts.append(max(PAGE_MIN, attempts[-1] // 2))
    last_err = None
    for n, attempt in enumerate(attempts):
        if _stop_now:
            raise Interrupted("interrupt")
        hi_try = min(lo + attempt - 1, hi)
        try:
            records = fetch_bisect(fetch_items_page, cat, lo, hi_try, log, [], "page")
            return records, hi_try
        except OsaError as exc:
            if _stop_now:
                raise Interrupted("interrupt") from None
            last_err = exc
            more = n < len(attempts) - 1
            log.warning(
                f"{cat}: page {lo}-{hi_try} failed ({exc})"
                + ("; retrying smaller" if more else "")
            )
    raise OsaError(str(last_err))


def build_plan(ccfg, idx, state, total, matches, skip_ranges):
    """[(lo, hi, why)] in export order: refresh, first, rest.

    Every range is clipped to [1, total + 1) and the skip-list ranges are
    taken out (finding 4, header L).
    """
    done = clip_ranges(state["done"], total)
    skipr = clip_ranges(skip_ranges, total)
    planned = []
    taken = list(skipr)
    if ccfg and idx is not None:
        refresh = subtract_ranges(
            clip_ranges([matches[p] for p in ccfg.refresh if p in matches], total),
            skipr,
        )
        planned += [(lo, hi, "refresh") for lo, hi in refresh]
        taken += refresh
        first = subtract_ranges(
            clip_ranges([matches[p] for p in ccfg.first if p in matches], total),
            done + taken,
        )
        planned += [(lo, hi, "first") for lo, hi in first]
        taken += first
    rest = subtract_ranges([(1, total + 1)], done + taken)
    planned += [(lo, hi, "rest") for lo, hi in rest]
    return planned


def progress_done(state, skip_ranges, total):
    """Items accounted for: done or under the skip list, inside [1, total]."""
    return covered_len(clip_ranges(list(state["done"]) + list(skip_ranges), total))


def catalogue_mount_points(c):
    if not c.volume:
        return []
    if c.volume == boot_volume_name():
        return ["/", "/System/Volumes/Data"]
    mp = f"/Volumes/{c.volume}"
    return [mp] if os.path.ismount(mp) else []


def dest_refusal(dest, catalogues):
    """None, or why dest must not receive stubs (header N)."""
    if dest == Path("/") or str(dest) == "/System/Volumes/Data":
        return "is the system volume"
    if dest == Path.home().resolve():
        return "is your home directory"
    if dest == Path("/Volumes"):
        return "is /Volumes itself"
    probe = dest
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        dev = probe.stat().st_dev
    except OSError:
        return None
    for c in catalogues:
        for mp in catalogue_mount_points(c):
            try:
                if os.stat(mp).st_dev == dev:
                    return (
                        f"is on the volume of catalogue {c.name!r} (mounted at "
                        f"{mp}); stubs must not land on the catalogued volume"
                    )
            except OSError:
                continue
    return None


def export_run(args, cfg, config_path):
    if args.list:  # table only; needs no dest, writes nothing, no log file
        try:
            catalogue_table(fetch_catalogues())
        except OsaError as exc:
            eprint(f"Error: {exc}")
            return 1
        return 0
    log = RunLog(args.log, enabled=not args.dry_run)
    progress = Progress(args.progress)
    t_start = time.time()
    dest = Path(args.dest or cfg.dest).expanduser().resolve()
    summary_bits = []
    problems = []
    exit_code = 0
    stop = None
    selected = []

    def fail(msg, code):
        eprint(f"Error: {msg}")
        log.error(msg)
        log.close()
        return code

    try:
        if not args.dry_run:
            if not dest.is_dir():
                return fail(
                    f"--dest {dest} does not exist or is not a directory "
                    f"(the batch script's --image flag mounts it).",
                    2,
                )
            if not os.access(dest, os.W_OK):
                return fail(f"--dest {dest} is not writable.", 1)
        why = dest_refusal(dest, [])
        if why:
            return fail(f"--dest {dest} {why}; refused.", 2)

        schedule_stop = None
        if not args.ignore_schedule and cfg.schedule:
            now = local_now()
            inside, schedule_stop = in_window(now, cfg.schedule)
            if not inside:
                nxt = next_window_start(now, cfg.schedule)
                print(
                    f"Outside schedule window "
                    f"({describe_schedule(cfg.schedule)}); next start "
                    f"{nxt or '?'}. Nothing done."
                )
                log.line(
                    f"outside schedule ({describe_schedule(cfg.schedule)}); exiting"
                )
                log.close()
                return 0

        if control_says_pause() and not args.dry_run:
            hint = f"resume with: {prog_name()} resume"
            print(f"held by control=pause; nothing done. {hint}")
            log.line(f"held by control=pause; nothing done; {hint}")
            log.close()
            return 0

        catalogues = fetch_catalogues()
        selected = select_catalogues(args, cfg, catalogues, log)
        if not selected:
            log.close()
            return 2
        seen = set()
        deduped = []
        for info in selected:
            if info.name not in seen:
                seen.add(info.name)
                deduped.append(info)
        selected = deduped
        why = dest_refusal(dest, selected)
        if why:
            return fail(f"--dest {dest} {why}; refused.", 2)

        other = running_pid(log)
        if other and not args.dry_run:
            return fail(
                f"another export is running (pid {other}, {pid_file()}); "
                f"pause or resume it, not a second run.",
                1,
            )
        if not args.dry_run:
            CTRL_DIR.mkdir(parents=True, exist_ok=True)
            pid_file().write_text(f"{os.getpid()}\n")
        log.info(
            f"dest={dest} page={args.page or cfg.page} "
            f"config={config_path} catalogues="
            f"{[c.name for c in selected]}"
        )

        try:
            for info in selected:
                stop = stop_reason_now(schedule_stop)
                if stop:
                    break
                ccfg = next(
                    (c for c in cfg.catalogs if c.name.lower() == info.name.lower()),
                    None,
                )
                if ccfg and not ccfg.enabled:
                    log.info(
                        f"{info.name}: disabled in config; explicit --catalog overrides"
                    )
                res = export_catalogue(
                    args,
                    cfg,
                    info,
                    ccfg,
                    dest,
                    log,
                    progress,
                    config_path,
                    schedule_stop,
                )
                if res["bit"]:
                    summary_bits.append(res["bit"])
                problems += [(info.name, pr) for pr in res["problems"]]
                if res["stop"]:
                    stop = res["stop"]
                    break
                if res["code"] != 0:
                    exit_code = res["code"]
                    break
        finally:
            if not args.dry_run:
                try:
                    if pid_file().read_text().strip() == str(os.getpid()):
                        pid_file().unlink()
                except OSError:
                    pass
    except OsaError as exc:
        if not _stop_now:
            return fail(str(exc), 1)
        stop = "interrupt"
    except (KeyboardInterrupt, Interrupted):
        stop = "interrupt"

    elapsed = time.time() - t_start
    print()
    print(f"Summary (elapsed {human_secs(elapsed)}):")
    for bit in summary_bits:
        print("  " + bit)
        log.line("summary: " + bit)
    if problems:
        print(f"  skipped items (first {SKIP_LIST_SHOWN} per catalogue):")
        for cat, pr in problems:
            print(f"    {cat}: {pr}")
            log.line(f"skipped: {cat}: {pr}")
    cats = [c.name for c in selected] or ["<catalogues>"]
    if stop in ("pause", "sigterm"):
        hint = resume_hint(dest, cats, config_path)
        why = "control=pause" if stop == "pause" else "SIGTERM"
        print(f"  PAUSED ({why}): state saved; {hint}")
        log.line(f"PAUSED ({why}); {hint}")
    elif stop == "schedule":
        hint = resume_hint(dest, cats, config_path)
        print(
            "  stopped at the schedule end: state saved; the next window "
            f"continues ({hint} --ignore-schedule)"
        )
        log.line("stopped at the schedule end")
    elif stop == "interrupt":
        print(
            "  interrupted: the partially-written page is not marked done; "
            "re-running rewrites it safely."
        )
        log.line("INTERRUPTED")
    if args.dry_run:
        print("dry run: nothing written")
    else:
        print(f"Aliases and stubs are under: {dest}")
    log.line(f"done, elapsed {human_secs(elapsed)}")
    log.close()
    if stop == "interrupt":
        return 130
    return exit_code


def export_catalogue(
    args, cfg, info, ccfg, dest, log, progress, config_path, schedule_stop
):
    """One catalogue. Returns {code, bit, stop, problems}."""
    cat = info.name
    cat_dir = dest / cat
    page_size = args.page or cfg.page
    limit = args.limit
    total_work = min(info.total, limit) if limit else info.total
    skip = cfg.skip_for(ccfg)
    res = {"code": 0, "bit": None, "stop": None, "problems": []}

    def failed(msg):
        eprint(f"Error: {msg}")
        log.error(msg)
        hint = resume_hint(dest, [cat], config_path)
        eprint(hint)
        log.error(hint)
        res["code"] = 1
        return res

    # --- dry run: one page, print, write nothing (not even state) ---------
    if args.dry_run:
        res["bit"] = dry_run_page(cat, info, total_work, page_size, skip)
        return res

    state = load_state(cat, dest, log)
    if args.restart:
        log.info(f"{cat}: --restart; clearing saved state for dest {dest}")
        state = fresh_state(cat, dest, info.lu_key)
        folders_journal(cat, dest).unlink(missing_ok=True)
    if state.get("lu_key") != info.lu_key and state["done"]:
        log.warning(
            f"{cat}: catalogue was updated since the saved state (last "
            f"updated {state.get('lu_key')} -> {info.lu_key}); resetting ranges"
        )
        state["done"] = []
    state["dest"] = str(dest)
    state["lu_key"] = info.lu_key
    state["last_updated"] = info.last_updated
    state["total"] = total_work

    def stop_check(where):
        reason = stop_reason_now(schedule_stop)
        if reason:
            raise StopRun(reason)

    # --- path index ---------------------------------------------------------
    idx = PathsIndex(info)
    if args.no_path_index:
        if ccfg and (ccfg.first or ccfg.refresh):
            msg = (
                f"{cat} has first/refresh prefixes in the config; they need "
                f"the path index (drop --no-path-index)."
            )
            eprint(f"Error: {msg}")
            log.error(msg)
            res["code"] = 1
            return res
        idx = None
    else:
        if not idx.valid_for(info, total_work, skip):
            if idx.txt.exists():
                log.info(f"{cat}: path index stale/outdated; rebuilding")
            try:
                idx.build(
                    info,
                    total_work,
                    page_size,
                    log,
                    progress,
                    stop_check,
                    skip,
                    args.log_interval,
                )
            except StopRun as st:
                res["stop"] = st.reason
                res["bit"] = (
                    f"{cat}: stopped during the path index pass ({st.reason}); "
                    f"nothing exported yet; output at {cat_dir}"
                )
                log.line(f"catalogue summary: {res['bit']}")
                return res
            except Interrupted:
                res["stop"] = "interrupt"
                res["bit"] = f"{cat}: interrupted during the path index pass"
                return res
            except OsaError as exc:
                if _stop_now:
                    res["stop"] = "interrupt"
                    res["bit"] = f"{cat}: interrupted during the path index pass"
                    return res
                return failed(f"{cat}: path index pass failed: {exc}")
        idx.load_meta()

    skipr = idx.skip_ranges if idx is not None else []
    skipped_by_list = covered_len(clip_ranges(skipr, total_work))
    matches = {}
    if idx is not None and ccfg:
        wanted = list(dict.fromkeys(ccfg.refresh + ccfg.first))
        matches = idx.match_prefixes(wanted, total_work)
        for pfx in wanted:
            if pfx not in matches:
                msg = (
                    f"{cat}: first/refresh prefix {pfx!r} matches no item"
                    + (f" within the first {total_work} (--limit)" if limit else "")
                    + "; prefixes are POSIX paths relative to the catalogue root"
                )
                eprint(f"warning: {msg}")
                log.warning(msg)

    plan = build_plan(ccfg, idx, state, total_work, matches, skipr)
    done_before = progress_done(state, skipr, total_work)
    log.info(
        f"{cat}: {info.total} items in catalogue, working on {total_work}, "
        f"{done_before} already done or skipped ({skipped_by_list} under the "
        f"skip list {skip}), {sum(hi - lo for lo, hi, _ in plan)} to export"
    )

    check_free_space(dest, total_work - done_before, cat, log)

    cat_dir.mkdir(parents=True, exist_ok=True)
    mounts = catalogue_mount_points(info)
    alias_root = mounts[0] if mounts and load_foundation(log) else None
    if alias_root:
        log.info(f"{cat}: files that exist under {alias_root} become Finder aliases")
    else:
        log.info(
            f"{cat}: "
            + ("volume not mounted" if not mounts else "no PyObjC")
            + "; every file becomes an empty stub"
        )
    journal = folders_journal(cat, dest)
    journal.parent.mkdir(parents=True, exist_ok=True)

    counts = PageCounts()
    t_cat = time.time()
    exported_here = 0
    stop = None
    try:
        with open(journal, "a", encoding="utf-8") as folder_fh:
            for range_lo, range_hi, why in plan:
                log.info(f"{cat}: exporting range {range_lo}-{range_hi - 1} ({why})")
                cursor = range_lo
                while cursor < range_hi:
                    stop = stop_reason_now(schedule_stop)
                    if stop:
                        break
                    try:
                        records, hi_done = fetch_page_with_retry(
                            cat, cursor, range_hi - 1, page_size, log
                        )
                    except OsaError as exc:
                        save_state(state, dest)
                        return failed(
                            f"{cat}: page {cursor}+ failed after retries: {exc}"
                        )
                    idx_rows = idx.get(cursor, hi_done) if idx is not None else None
                    page_counts = write_page(
                        records,
                        idx_rows,
                        cat_dir,
                        folder_fh,
                        cursor,
                        idx,
                        skip,
                        log,
                        alias_root,
                    )
                    folder_fh.flush()
                    counts.add(page_counts)
                    exported_here += hi_done + 1 - cursor
                    add_done(state, cursor, hi_done + 1)
                    done_now = progress_done(state, skipr, total_work)
                    state["counts"] = {"items": done_now, "finished": False}
                    save_state(state, dest)
                    progress.line(cat, done_now, total_work, why)
                    log.heartbeat(
                        progress.stat_line(cat, done_now, total_work, base=done_before),
                        interval=args.log_interval,
                    )
                    log.info(
                        f"{cat}: page {cursor}-{hi_done} done "
                        f"({page_counts.items} written: "
                        f"{page_counts.aliases} aliases, {page_counts.stubs} "
                        f"stubs, {page_counts.folders} folders; "
                        f"{page_counts.skipped} skipped)"
                    )
                    check_free_space(dest, total_work - done_now, cat, log)
                    cursor = hi_done + 1
                if stop:
                    break
    except StubWriteError as exc:
        save_state(state, dest)
        return failed(f"{cat}: {exc}")
    except (KeyboardInterrupt, Interrupted):
        stop = "interrupt"

    # completion: refresh cleanup FIRST, then folder mtimes (finding 18)
    done_now = progress_done(state, skipr, total_work)
    fully_done = done_now >= total_work and not stop
    if fully_done:
        if ccfg and ccfg.refresh and idx is not None and not limit:
            # With --limit the keep-set only covers the clipped range, so
            # stubs of catalogue items beyond the limit would count as
            # "stale"; removal is a whole-catalogue operation.
            for pfx in ccfg.refresh:
                if pfx in matches:
                    lo, hi = matches[pfx]
                    remove_stale_stubs(cat_dir, pfx, idx.rel_set(lo, hi), log)
        elif ccfg and ccfg.refresh and limit:
            log.info(f"{cat}: --limit set; skipping refresh stale-stub removal")
        apply_folder_mtimes(cat, dest, cat_dir, log)
        state["finished"] = True
        state["counts"] = {"items": done_now, "finished": True}
    else:
        state["finished"] = False
    save_state(state, dest)

    elapsed_cat = time.time() - t_cat
    rate = exported_here / elapsed_cat if elapsed_cat > 1 else 0.0
    unreadable = counts.skipped - counts.failed
    bit = (
        f"{cat}: {exported_here} items processed in {human_secs(elapsed_cat)}"
        + (f" ({rate:.1f} items/s)" if rate else "")
        + f": {counts.files} files ({counts.aliases} aliases, {counts.stubs} "
        f"stubs), {counts.folders} folders written; skipped "
        f"{skipped_by_list} under the skip list (not fetched), {unreadable} "
        f"unparseable/unreadable, {counts.failed} write errors; "
        f"{done_now}/{total_work} done"
        + (
            ""
            if total_work == info.total
            else f" (catalogue has {info.total}; --limit)"
        )
        + (", complete" if fully_done else "")
        + (", PAUSED" if stop in ("pause", "sigterm") else "")
        + (", stopped at schedule end" if stop == "schedule" else "")
        + (", interrupted" if stop == "interrupt" else "")
        + f"; output at {cat_dir}"
    )
    log.line(f"catalogue summary: {bit}")
    res["bit"] = bit
    res["stop"] = stop
    res["problems"] = counts.problems
    return res


def dry_run_page(cat, info, total_work, page_size, skip):
    if total_work < 1:
        return f"{cat}: dry run skipped (no items)"
    hi = min(page_size, total_work, info.total)
    t0 = time.time()
    records = fetch_items_page(cat, 1, hi)
    dt_s = max(time.time() - t0, 1e-6)
    print(
        f"{cat}: dry run, first page 1-{hi} ({len(records)} records) "
        f"fetched in {dt_s:.1f} s ({len(records) / dt_s:.1f} items/s)"
    )
    shown = 0
    skipped = 0
    for rec in records:
        rel = hfs_to_rel(rec.complete_path)
        if rel is None:
            continue
        if skip and _skip_match(rel, skip):
            skipped += 1
            continue
        if shown < 10:
            kind = "dir " if rec.kind.strip().lower() == "folder" else "file"
            print(f"  would write {kind} <dest>/{cat}/{rel or ''}")
            shown += 1
    if skipped:
        print(f"  {skipped} of these {len(records)} are under the skip list {skip}")
    remaining = max(0, total_work - hi)
    per_item = dt_s / max(1, len(records))
    print(
        f"  projected fetch for the remaining {remaining} items: "
        f"~{human_secs(remaining * per_item)} (plus writing)"
    )
    return f"{cat}: dry run ok, page rate {len(records) / dt_s:.1f} items/s"


# --------------------------------------------------------------------------
# catalogue selection, listing, mount status
# --------------------------------------------------------------------------

_boot_volume = None


def boot_volume_name():
    global _boot_volume
    if _boot_volume is None:
        try:
            proc = subprocess.run(
                ["diskutil", "info", "-plist", "/"],
                capture_output=True,
                text=True,
                check=False,
            )
            _boot_volume = plistlib.loads(proc.stdout.encode()).get("VolumeName", "")
        except (OSError, ValueError, TypeError, AttributeError):
            _boot_volume = ""
    return _boot_volume


def volume_status(volume):
    if not volume:
        return "offline (no volume name)"
    if volume == boot_volume_name():
        return f"volume mounted (boot volume '{volume}')"
    if os.path.isdir(f"/Volumes/{volume}"):
        return f"volume mounted (/Volumes/{volume})"
    return f"offline (/Volumes/{volume} not mounted)"


def volume_mounted(volume):
    if not volume:
        return False
    return volume == boot_volume_name() or os.path.isdir(f"/Volumes/{volume}")


def catalogue_table(catalogues):
    print(
        f"{'Catalogue':<18}{'Volume':<18}{'Items':>12}{'Files':>12}"
        f"{'Folders':>10}  Status"
    )
    for c in catalogues:
        print(
            f"{c.name[:17]:<18}{(c.volume or '-')[:17]:<18}"
            f"{c.total:>12,}{c.files:>12,}{c.folders:>10,}  "
            f"{volume_status(c.volume)}"
        )


def select_catalogues(args, cfg, catalogues, log):
    """The catalogues to export, or None (after a logged error, exit 2)."""
    names_lower = {c.name.lower(): c for c in catalogues}

    def err(msg):
        eprint(f"Error: {msg}")
        log.error(msg)

    if args.all or args.offline:
        picked = (
            catalogues
            if args.all
            else [c for c in catalogues if not volume_mounted(c.volume)]
        )
        if not picked:
            return err(
                "--offline found no catalogue whose volume is offline (all "
                "mounted right now)."
            )
        return picked
    if args.catalog:
        picked = []
        for name in args.catalog:
            info = names_lower.get(name.lower())
            if not info:
                return err(
                    f"no NeoFinder catalogue named {name!r} "
                    f"(have: {', '.join(c.name for c in catalogues)})."
                )
            picked.append(info)
        return picked
    enabled = [c for c in cfg.catalogs if c.enabled]
    if enabled:
        picked = []
        for ccfg in enabled:
            info = names_lower.get(ccfg.name.lower())
            if not info:
                return err(
                    f"config names catalogue {ccfg.name!r} but NeoFinder has "
                    f"none by that name."
                )
            picked.append(info)
        return picked
    catalogue_table(catalogues)
    return err(
        "no catalogue selected. A multi-million-item export must be "
        "explicit: pass --catalog NAME (repeatable), --all or --offline, or "
        "list [[catalog]] entries in the config."
    )


# --------------------------------------------------------------------------
# launchd subcommands
# --------------------------------------------------------------------------


def plist_path():
    return Path("~/Library/LaunchAgents").expanduser() / f"{LABEL}.plist"


def run_launchctl(cmd, dry_run):
    print("+ " + " ".join(cmd))
    if dry_run:
        return 0, ""
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        print(f"  launchctl exited {proc.returncode}: {out[:400]}")
    return proc.returncode, out


def stable_python():
    """sys.executable unresolved, or the /opt/homebrew/bin/python3.X link
    when it is the same interpreter: the versioned Cellar path that
    resolve() gives disappears on `brew cleanup` (finding 10)."""
    exe = sys.executable
    link = Path(f"/opt/homebrew/bin/python{sys.version_info[0]}.{sys.version_info[1]}")
    try:
        if link.exists() and link.resolve() == Path(exe).resolve():
            return str(link)
    except OSError:
        pass
    return exe


def agent_loaded():
    return (
        subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def render_plist(cfg, config_path, interval=None):
    template_path = Path(__file__).resolve().parent / PLIST_TEMPLATE
    if not template_path.exists():
        raise SystemExit(f"template not found: {template_path}")
    text = template_path.read_text()
    if interval is not None:
        triggers = f"\t<key>StartInterval</key>\n\t<integer>{int(interval)}</integer>"
    else:
        entries = []
        hour, minute = divmod(cfg.schedule.start, 60)
        for day in sorted(cfg.schedule.days):
            wd = (day + 1) % 7  # python 0=Mon -> launchd 1=Mon, 0=Sun
            entries.append(
                f"\t\t<dict>\n"
                f"\t\t\t<key>Weekday</key><integer>{wd}</integer>\n"
                f"\t\t\t<key>Hour</key><integer>{hour}</integer>\n"
                f"\t\t\t<key>Minute</key><integer>{minute}</integer>\n"
                f"\t\t</dict>"
            )
        triggers = (
            "\t<key>StartCalendarInterval</key>\n\t<array>\n"
            + "\n".join(entries)
            + "\n\t</array>"
        )
    for key, value in (
        ("@PYTHON@", stable_python()),
        ("@SCRIPT@", str(Path(__file__).resolve())),
        ("@CONFIG@", str(Path(config_path).expanduser().resolve())),
        ("@LOGDIR@", str(LOG_DIR)),
    ):
        text = text.replace(key, xml_escape(value))
    text = text.replace("@TRIGGERS@", triggers)
    plistlib.loads(text.encode())  # validate before writing
    return text


def cmd_install(args):
    cfg, _config_path = load_config(args.config)
    if args.interval is None and cfg.schedule is None:
        msg = (
            "install needs a [schedule] in the config (the agent must know "
            "when to run), or pass --interval SECONDS for a plain "
            "StartInterval agent."
        )
        eprint(f"Error: {msg}")
        subcmd_log(f"install refused: {msg}")
        return 2
    if not any(c.enabled for c in cfg.catalogs):
        msg = (
            f"install needs a config that selects a catalogue (an enabled "
            f"[[catalog]] entry in {Path(args.config).expanduser()}); without "
            f"one every scheduled run would exit 2 with the catalogue table."
        )
        eprint(f"Error: {msg}")
        subcmd_log(f"install refused: {msg}")
        return 2
    text = render_plist(cfg, args.config, interval=args.interval)
    print(f"Rendered LaunchAgent {LABEL} (config {Path(args.config).expanduser()}):")
    print(text)
    plist = plist_path()
    target = f"gui/{os.getuid()}/{LABEL}"
    bootout = ["launchctl", "bootout", target]
    bootstrap = ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)]
    loaded = agent_loaded()
    if args.dry_run:
        print("(dry run: nothing written, nothing bootstrapped)")
        if loaded:
            print("agent already loaded; it would be booted out first")
            print("+ " + " ".join(bootout))
        print("+ " + " ".join(["mkdir", "-p", str(plist.parent)]))
        print(f"+ write {plist}")
        print("+ " + " ".join(bootstrap))
        return 0
    if loaded:
        print(
            "agent already loaded; booting it out first (a running export "
            "gets SIGTERM, finishes its page and saves state)"
        )
        rc, _ = run_launchctl(bootout, False)
        subcmd_log(f"install: bootout of the loaded agent rc={rc}")
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(text)
    print(f"wrote {plist}")
    rc, _ = run_launchctl(bootstrap, False)
    subcmd_log(f"install: bootstrap rc={rc} plist={plist}")
    if rc != 0:
        eprint("Error: launchctl bootstrap failed (see the output above).")
        return 1
    print(f"installed: {target}")
    print(
        "first scheduled run: start it once by hand while at the keyboard "
        f"(launchctl kickstart {target}) to answer the Automation prompt"
    )
    return 0


def cmd_remove(args):
    plist = plist_path()
    rc, _ = run_launchctl(
        ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], args.dry_run
    )
    if args.dry_run:
        print(f"+ rm -f {plist}")
    else:
        if rc != 0:
            print("  (bootout failed — the agent was probably not loaded)")
        if plist.exists():
            plist.unlink()
            print(f"deleted {plist}")
        subcmd_log(f"remove: bootout rc={rc}")
    print(f"state and path index kept in {CTRL_DIR}")
    return 0


def cmd_enable_disable(args, enable):
    verb = "enable" if enable else "disable"
    rc, _ = run_launchctl(
        ["launchctl", verb, f"gui/{os.getuid()}/{LABEL}"], args.dry_run
    )
    if not args.dry_run:
        subcmd_log(f"{verb}: rc={rc}")
    return rc


_LIBC.getxattr.argtypes = [
    ctypes.c_char_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_uint32,
    ctypes.c_int,
]
_LIBC.getxattr.restype = ctypes.c_ssize_t


def get_raw_xattr(path, name):
    """The bytes of xattr `name`, or None when absent/unreadable."""
    p, n = os.fsencode(path), name.encode()
    size = _LIBC.getxattr(p, n, None, 0, 0, 0)
    if size <= 0:
        return None
    buf = ctypes.create_string_buffer(size)
    got = _LIBC.getxattr(p, n, buf, size, 0, 0)
    return buf.raw[:got] if got > 0 else None


def get_plist_xattr(path, name):
    """The decoded binary-plist xattr `name`, or None when absent/unreadable."""
    blob = get_raw_xattr(path, name)
    if blob is None:
        return None
    try:
        return plistlib.loads(blob)
    except Exception:
        return None


def copy_last_used(real, alias):
    """Copy the real file's last-opened date onto the alias (header R).

    True when the real file has one; writes only when the alias differs.
    """
    data = get_raw_xattr(real, LASTUSED_XATTR)
    if data is None:
        return False
    if get_raw_xattr(alias, LASTUSED_XATTR) != data:
        rc = _LIBC.setxattr(
            os.fsencode(alias), LASTUSED_XATTR.encode(), data, len(data), 0, 0
        )
        if rc != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), alias)
    return True


def bookmark_path(path):
    """The real file's path recorded in the alias file at `path`, or None.

    Reads the bookmark's stored path without resolving or mounting
    anything; None without PyObjC or for a non-alias file.
    """
    F = _F
    if not F:
        return None
    data, _err = F.NSURL.bookmarkDataWithContentsOfURL_error_(
        F.NSURL.fileURLWithPath_(path), None
    )
    if data is None:
        return None
    vals = F.NSURL.resourceValuesForKeys_fromBookmarkData_([F.NSURLPathKey], data)
    real = vals.get(F.NSURLPathKey) if vals is not None else None
    return str(real) if real else None


def cmd_retag(args):
    """Apply tags/keywords (headers P, Q) to an existing batch volume."""
    root = Path(args.path).expanduser()
    try:
        resolved = root.resolve()
    except OSError as exc:
        eprint(f"retag: cannot resolve {root}: {exc}")
        return 2
    if resolved == Path("/"):
        eprint("retag: refusing /")
        return 2
    if not root.is_dir():
        eprint(f"retag: {root} is not a directory")
        return 2
    seen = errors = untagged = 0
    per_group = {}
    per_tag = {}
    real_read = last_used = 0
    shown = 0
    deadline = getattr(args, "deadline", None)
    stopped = False
    load_foundation(RunLog(enabled=False))
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if deadline is not None and time.time() >= deadline:
            stopped = True
            break
        for fname in filenames:
            if fname.startswith((ALIAS_TMP_PREFIX, "._")):
                continue
            path = os.path.join(dirpath, fname)
            try:
                if not stat.S_ISREG(os.lstat(path).st_mode):
                    continue
                st_size = os.lstat(path).st_size
                seen += 1
                kind = get_plist_xattr(path, KIND_XATTR)
                group = kind_group(fname, kind if isinstance(kind, str) else "")
                comment = get_plist_xattr(path, FINDER_COMMENT_XATTR)
                m = COMMENT_SIZE_RE.search(comment) if isinstance(comment, str) else None
                size = int(m.group(1)) if m else 0
                offline = st_size == 0  # a stub; an alias is a ~1 KB bookmark
                user_tags = None
                if not offline:
                    real = bookmark_path(path)
                    if real is not None and os.path.exists(real):
                        user_tags = real_user_tags(real)
                        real_read += 1
                        if args.dry_run:
                            has_lu = get_raw_xattr(real, LASTUSED_XATTR) is not None
                        else:
                            has_lu = copy_last_used(real, path)
                        last_used += has_lu
                if user_tags is None:  # keep what an earlier run copied
                    user_tags = [
                        t for t in real_user_tags(path) if not t.startswith("nf-")
                    ]
                nf = nf_tags(group, size, offline)
                if not nf and not user_tags:
                    untagged += 1
                    continue
                if not args.dry_run:
                    set_nf_tags(path, group, size, offline, user_tags)
                if group:
                    per_group[group] = per_group.get(group, 0) + 1
                else:
                    untagged += 1
                for t in nf[1 if group else 0:] + (["(real tags)"] if user_tags else []):
                    per_tag[t] = per_tag.get(t, 0) + 1
            except OSError as exc:
                errors += 1
                if shown < SKIP_LIST_SHOWN:
                    shown += 1
                    eprint(f"retag: {path}: {exc}")
            if seen and seen % 50000 == 0:
                eprint(f"retag: {seen} files so far")
    verb = "would tag" if args.dry_run else "tagged"
    tagged = sum(per_group.values())
    print(
        f"retag {root}: {seen} files seen, {verb} {tagged} with a kind, "
        f"{untagged} without, {errors} errors; real files read for tags: {real_read}, "
        f"last opened copied: {last_used}"
        + ("; STOPPED at the deadline" if stopped else "")
    )
    for group in sorted(per_group, key=lambda g: (-per_group[g], g)):
        print(f"  nf-{group:<10} {per_group[group]}")
    for tag in sorted(per_tag, key=lambda t: (-per_tag[t], t)):
        print(f"  {tag:<13} {per_tag[tag]}")
    if not args.dry_run:
        subcmd_log(
            f"retag {root}: seen={seen} kind_tagged={tagged} no_kind={untagged} "
            f"errors={errors} real_read={real_read} last_used={last_used} "
            f"stopped={int(stopped)} "
            + " ".join(f"{t}={n}" for t, n in sorted(per_tag.items()))
        )
    return 1 if errors else 3 if stopped else 0


STUB_DATES_SCRIPT = (
    WALLREF_HANDLER
    + """
on run
	set refD to my wallRef()
	set ns to {@NS@}
	set cds to {}
	set cps to {}
	with timeout of @AET@ seconds
		tell application "NeoFinder"
			repeat with n in ns
				try
					set {cd, cp} to {Creation Date, complete path} of Catalog Item (n as integer) of Catalogue "@CAT@"
				on error
					set {cd, cp} to {missing value, ""}
				end try
				set end of cds to cd
				set end of cps to cp
			end repeat
		end tell
	end timeout
	set US to character id 31
	set RS to character id 30
	set out to {}
	repeat with i from 1 to count of cds
		set d to item i of cds
		if class of d is date then
			set d2 to ((d - refD) as text)
		else
			set d2 to ""
		end if
		try
			set p2 to (item i of cps) as text
		on error
			set p2 to ""
		end try
		set end of out to d2 & US & p2
	end repeat
	set {TID, AppleScript's text item delimiters} to {AppleScript's text item delimiters, RS}
	set o to out as text
	set AppleScript's text item delimiters to TID
	return o
end run
"""
)


def neofinder_running():
    return subprocess.run(["pgrep", "-xq", "NeoFinder"]).returncode == 0


def cmd_stub_dates(args):
    """Stubs' creation and added dates from NeoFinder's Creation Date (R)."""
    root = Path(args.path).expanduser()
    if not root.is_dir():
        eprint(f"stub-dates: {root} is not a directory")
        return 2
    if not neofinder_running():
        print("stub-dates: NeoFinder is not running; nothing asked")
        return 0
    deadline = getattr(args, "deadline", None)
    want = {}  # catalogue -> {rel: (stub path, complete path from comment)}
    done_before = 0
    for cat_dir in sorted(root.iterdir()):
        if cat_dir.name.startswith(".") or not cat_dir.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(cat_dir):
            for fname in filenames:
                if fname.startswith((ALIAS_TMP_PREFIX, "._")):
                    continue
                path = os.path.join(dirpath, fname)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_size != 0:
                    continue
                if get_raw_xattr(path, STUB_CRTIME_XATTR) is not None:
                    done_before += 1
                    continue
                comment = get_plist_xattr(path, FINDER_COMMENT_XATTR)
                m = COMMENT_PATH_RE.match(comment) if isinstance(comment, str) else None
                if m:
                    rel = os.path.relpath(path, cat_dir)
                    want.setdefault(cat_dir.name, {})[rel] = (path, m.group(1))
    fixed = mismatch = no_index = no_date = failed = 0
    stopped = False
    for cat, rels in want.items():
        idx = PathsIndex(Catalogue(cat, None, 0, 0, None, None))
        if not idx.txt.exists():
            no_index += len(rels)
            continue
        nums = {}
        with open(idx.txt, encoding="utf-8") as fh:
            for i, line in enumerate(fh, start=1):
                flag, _, rel = line.rstrip("\n").partition(US)
                if flag == "f" and rel in rels:
                    nums[i] = rel
        no_index += len(rels) - len(nums)
        order = sorted(nums)
        for k in range(0, len(order), STUB_DATES_CHUNK):
            if deadline is not None and time.time() >= deadline:
                stopped = True
                break
            chunk = order[k : k + STUB_DATES_CHUNK]
            script = (
                STUB_DATES_SCRIPT.replace("@NS@", ", ".join(map(str, chunk)))
                .replace("@AET@", str(AE_TIMEOUT))
                .replace("@CAT@", asa_quote(cat))
            )
            try:
                out = osa(script)
            except OsaError as exc:
                eprint(f"stub-dates: {cat}: {exc}")
                failed += len(chunk)
                continue
            recs = out.split(RS)
            if len(recs) != len(chunk):
                eprint(f"stub-dates: {cat}: {len(recs)} answers for {len(chunk)} items")
                failed += len(chunk)
                continue
            for n, rec in zip(chunk, recs):
                path, want_cp = rels[nums[n]]
                d, _, cp = rec.partition(US)
                if cp != want_cp:
                    mismatch += 1  # the catalogue changed since the export
                    continue
                rel_w = parse_num(d) if d else None
                epoch = None if rel_w is None else wall_to_epoch(rel_w + WALL_REF_EPOCH)
                if epoch is None:
                    no_date += 1
                    continue
                if not args.dry_run:
                    try:
                        set_creation_time(path, epoch)
                        set_added_time(path, epoch)
                        _set_plist_xattr(path, STUB_CRTIME_XATTR, int(epoch))
                    except OSError as exc:
                        eprint(f"stub-dates: {path}: {exc}")
                        failed += 1
                        continue
                fixed += 1
        if stopped:
            break
    todo = sum(len(r) for r in want.values())
    verb = "would set" if args.dry_run else "set"
    print(
        f"stub-dates {root}: {todo} stubs to ask about ({done_before} done before); "
        f"{verb} {fixed}, path mismatch {mismatch}, not in the path index {no_index}, "
        f"no date {no_date}, failed {failed}"
        + ("; STOPPED at the deadline" if stopped else "")
    )
    if not args.dry_run:
        subcmd_log(
            f"stub-dates {root}: todo={todo} done_before={done_before} set={fixed} "
            f"mismatch={mismatch} no_index={no_index} no_date={no_date} "
            f"failed={failed} stopped={int(stopped)}"
        )
    return 1 if failed else 3 if stopped else 0


def cmd_nightly(args):
    """Attach the batch image if needed, retag, stub-dates, detach (R)."""
    mount = Path(args.mount)
    image = Path(args.image).expanduser()
    try:
        stop_min = _parse_hhmm(args.stop_by)
    except ValueError as exc:
        eprint(f"nightly: {exc}")
        return 2
    deadline = _next_occurrence(local_now(), stop_min).timestamp()
    if args.index:
        deadline -= INDEX_MARGIN_S
    # SIGTERM (Jobber's timeout backstop) unwinds through `finally`.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(143))
    attached = indexed = False
    if args.index and os.path.ismount(mount):
        _index_applier("off")
    if not os.path.ismount(mount):
        if not image.exists():
            eprint(f"nightly: no image {image}")
            subcmd_log(f"nightly: no image {image}")
            return 2
        r = subprocess.run(
            ["hdiutil", "attach"]
            + ([] if args.index else ["-nobrowse"])
            + ["-mountpoint", str(mount), str(image)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip()
            eprint(f"nightly: attach failed: {msg}")
            subcmd_log(f"nightly: attach {image} failed: {msg}")
            return 2
        attached = True
    rt = sd = det = 0
    try:
        common = dict(path=str(mount), dry_run=False, deadline=deadline)
        rt = cmd_retag(argparse.Namespace(**common))
        sd = cmd_stub_dates(argparse.Namespace(**common)) if rt != 3 else 3
        if args.index:
            indexed = _index_applier("on") == 0
    finally:
        if attached and not indexed:
            r = subprocess.run(
                ["hdiutil", "detach", str(mount)], capture_output=True, text=True
            )
            det = r.returncode
            if det != 0:
                eprint(f"nightly: detach failed: {(r.stderr or r.stdout).strip()}")
        subcmd_log(
            f"nightly: retag={rt} stub-dates={sd} attached={int(attached)} "
            f"indexed={int(indexed)} detach={det}"
        )
    return max(rt, sd, 1 if det else 0, 1 if args.index and not indexed else 0)


def _index_applier(verb):
    """Run the root-owned index applier (on|off) through `sudo -n`; log and
    return its exit status (127 when it is not installed)."""
    if not os.path.exists(INDEX_APPLIER):
        msg = f"{INDEX_APPLIER} not installed (just setup in macos/neofinder/)"
        eprint(f"nightly: {msg}")
        subcmd_log(f"nightly: index {verb}: {msg}")
        return 127
    r = subprocess.run(
        ["sudo", "-n", INDEX_APPLIER, verb], capture_output=True, text=True
    )
    out = (r.stdout + r.stderr).strip()
    print(f"nightly: index {verb}: rc={r.returncode} {out}")
    subcmd_log(f"nightly: index {verb}: rc={r.returncode} {out}")
    return r.returncode


def pid_file():
    return CTRL_DIR / "run.pid"


def running_pid(log=None):
    """The exporter's pid from run.pid, trusted only when `ps` shows that
    pid running this script (finding 8: pids are reused after a SIGKILL or
    reboot). A stale pid file is removed and logged."""
    pf = pid_file()
    try:
        raw = pf.read_text().strip()
    except OSError:
        return None
    try:
        pid = int(raw)
    except ValueError:
        pid = None
    cmd = ""
    if pid:
        proc = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        cmd = proc.stdout.strip()
        if SCRIPT_NAME in cmd:
            return pid
    what = "not running" if not cmd else f"is not an exporter: {cmd[:80]}"
    msg = f"removed stale pid file {pf} (pid {raw!r} {what})"
    try:
        pf.unlink()
    except OSError:
        return None
    subcmd_log(msg)
    if log is not None:
        log.info(msg)
    else:
        print(msg)
    return None


def cmd_pause(args):
    CTRL_DIR.mkdir(parents=True, exist_ok=True)
    (CTRL_DIR / "control").write_text("pause\n")
    pid = running_pid()
    if pid:
        print(f"+ kill -TERM {pid} (export pid from {pid_file()})")
        os.kill(pid, signal.SIGTERM)
        print(
            "pause requested; the export finishes its current page, "
            "saves state and exits 0"
        )
    else:
        print(
            f"control=pause written; no export is running. Every later "
            f"export, the nightly agent's too, is held at once until: "
            f"{prog_name()} resume"
        )
    subcmd_log(f"pause (pid {pid or 'none'})")
    return 0


def cmd_resume(args):
    CTRL_DIR.mkdir(parents=True, exist_ok=True)
    (CTRL_DIR / "control").write_text("run\n")
    if agent_loaded():
        rc, _ = run_launchctl(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"], args.dry_run
        )
        subcmd_log(f"resume: kickstart rc={rc}")
        return rc
    if not getattr(args, "now", False):
        cfg_arg = f" --config {args.config}" if args.config != CONFIG_DEFAULT else ""
        print(
            "control=run (unpaused); no agent is installed, so nothing was "
            "started. Continue with one of:\n"
            f"  {prog_name()} export{cfg_arg}      foreground run\n"
            f"  {prog_name()} resume --now{cfg_arg}  the same, from here\n"
            f"  {prog_name()} install{cfg_arg}     the LaunchAgent, then "
            f"launchctl kickstart -k gui/$UID/{LABEL}"
        )
        subcmd_log("resume: flag cleared, no agent, no --now")
        return 0
    print(
        "agent not installed; starting a foreground export (Ctrl-C pauses it)",
        flush=True,
    )
    subcmd_log("resume: foreground export (--now)")
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "export",
            "--config",
            str(Path(args.config).expanduser()),
        ],
        check=False,
    )
    return proc.returncode


def cmd_status(args):
    cfg, _config_path = load_config(args.config)
    rc = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if rc.returncode == 0:
        state_line = next(
            (ln for ln in rc.stdout.splitlines() if "state =" in ln), ""
        ).strip()
        print(f"agent:    installed ({state_line or 'loaded'})")
    else:
        print("agent:    not installed")
    dis = subprocess.run(
        ["launchctl", "print-disabled", f"gui/{os.getuid()}"],
        capture_output=True,
        text=True,
        check=False,
    )
    tail = dis.stdout.split(f'"{LABEL}"')[-1][:30] if LABEL in dis.stdout else ""
    disabled = "disabled" in tail or "=> true" in tail
    print(f"enabled:  {'no' if disabled else 'yes'}")
    pid = running_pid()
    print(f"running:  {'yes (pid ' + str(pid) + ')' if pid else 'no'}")
    print(f"paused:   {'yes' if control_says_pause() else 'no'}")
    print(f"config:   {Path(args.config).expanduser()}")
    print(f"schedule: {describe_schedule(cfg.schedule)}")
    now = local_now()
    inside, stop_at = in_window(now, cfg.schedule)
    nxt = next_window_start(now, cfg.schedule)
    print(
        f"window:   {'inside' if inside else 'outside'}"
        + (f" (stops {stop_at})" if stop_at else "")
        + (f"; next start {nxt}" if nxt else "")
    )
    states = sorted((CTRL_DIR / "state").glob("*/*.json"))
    if not states:
        print("progress: no state files yet")
    else:
        by_dest = {}
        for p in states:
            try:
                st = json.loads(p.read_text())
            except (ValueError, OSError):
                print(f"  (unreadable state file {p})")
                continue
            by_dest.setdefault(st.get("dest", f"? ({p.parent.name})"), []).append(
                (p, st)
            )
        print("progress (per dest):")
        for dest_s, items in sorted(by_dest.items()):
            print(f"  {dest_s}:")
            for p, st in items:
                tot = st.get("total") or 0
                done = (st.get("counts") or {}).get("items")
                if done is None:
                    done = covered_len(clip_ranges(st.get("done", []), tot))
                fin = ", finished" if st.get("finished") else ""
                print(
                    f"    {p.stem}: {done:,}/{tot:,} done{fin} "
                    f"(updated {st.get('updated', '?')})"
                )
    latest = LOG_DIR / "latest.log"
    if latest.exists():
        try:
            last = [ln for ln in latest.read_text().splitlines() if ln.strip()][-1]
            print(f"last log: {last[:160]}")
        except OSError:
            pass
    else:
        print("last log: none yet")
    return 0


# --------------------------------------------------------------------------
# main / argument parsing
# --------------------------------------------------------------------------


def add_export_flags(parser):
    parser.add_argument(
        "--dest",
        help=f"staging directory (default {DEST_DEFAULT}; must exist and be writable)",
    )
    parser.add_argument(
        "--catalog", action="append", default=[], help="catalogue name (repeatable)"
    )
    parser.add_argument("--all", action="store_true", help="export every catalogue")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="export every catalogue whose volume is not mounted",
    )
    parser.add_argument(
        "--page", type=int, help=f"items per AppleScript page (default {PAGE_DEFAULT})"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="export only the first N items per catalogue (testing)",
    )
    parser.add_argument(
        "--progress", action="store_true", help="live progress and ETA on stderr"
    )
    parser.add_argument(
        "--log",
        help="log file (default "
        "~/Library/Logs/neofinder-stub-export/<ts>.log + "
        "latest.log symlink)",
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        help=f"log heartbeat seconds (default {LOG_INTERVAL_DEFAULT})",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="ignore and clear saved state: a full re-export (turns stubs "
        "written before aliases existed into aliases; volume must be mounted)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch one page per catalogue, print what would be written, write nothing",
    )
    parser.add_argument(
        "--list", action="store_true", help="print the catalogue table and exit 0"
    )
    parser.add_argument(
        "--ignore-schedule",
        action="store_true",
        help="run even outside the config schedule window",
    )
    parser.add_argument(
        "--no-path-index",
        action="store_true",
        help="skip the path index pass (disables first/refresh prefixes)",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog=SCRIPT_NAME,
        description=__doc__.split("\n\n")[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd")

    exp = sub.add_parser("export", help="the run (default)")
    add_export_flags(exp)
    exp.add_argument(
        "--config",
        default=CONFIG_DEFAULT,
        help=f"TOML config (default {CONFIG_DEFAULT})",
    )

    inst = sub.add_parser("install", help="render and install the LaunchAgent")
    inst.add_argument(
        "--config",
        default=CONFIG_DEFAULT,
        help=f"TOML config (default {CONFIG_DEFAULT})",
    )
    inst.add_argument(
        "--interval", type=int, help="use StartInterval SECONDS instead of a schedule"
    )
    inst.add_argument(
        "--dry-run",
        action="store_true",
        help="print the rendered plist and launchctl commands",
    )

    for name, helptext in (
        ("remove", "boot out and delete the agent"),
        ("enable", "clear the disable flag"),
        ("disable", "set the disable flag"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--dry-run", action="store_true")

    sub.add_parser("pause", help="pause the running export")
    for name in ("resume", "restart"):
        sp = sub.add_parser(name, help="unpause (kickstart the agent)")
        sp.add_argument(
            "--now",
            action="store_true",
            help="with no agent installed, also start a foreground export "
            "(default: only clear the pause flag and say how to continue)",
        )
        sp.add_argument(
            "--config",
            default=CONFIG_DEFAULT,
            help=f"TOML config (default {CONFIG_DEFAULT})",
        )
        sp.add_argument("--dry-run", action="store_true")

    st = sub.add_parser("status", help="show agent/run state")
    st.add_argument(
        "--config",
        default=CONFIG_DEFAULT,
        help=f"TOML config (default {CONFIG_DEFAULT})",
    )

    sub.add_parser("list", help="print the catalogue table")

    rt = sub.add_parser(
        "retag", help="(re)write kind tags and keywords on an existing batch volume"
    )
    rt.add_argument("path", help="batch volume or directory to walk")
    rt.add_argument(
        "--dry-run", action="store_true", help="print group counts, write nothing"
    )

    sd = sub.add_parser(
        "stub-dates",
        help="set stubs' creation and added dates from NeoFinder's Creation Date",
    )
    sd.add_argument("path", help="batch volume or directory to walk")
    sd.add_argument("--dry-run", action="store_true", help="count, write nothing")

    ng = sub.add_parser(
        "nightly",
        help="attach the batch image if needed, retag, stub-dates, then detach"
        " (or, with --index, index it and leave it attached)",
    )
    ng.add_argument("--image", default=NIGHTLY_IMAGE, help="sparse image to attach")
    ng.add_argument("--mount", default=NIGHTLY_MOUNT, help="its mount point")
    ng.add_argument(
        "--stop-by", default="05:45", help="HH:MM local time when work stops"
    )
    ng.add_argument(
        "--index",
        action="store_true",
        help="leave the volume attached and Spotlight-indexed (needs `just setup`)",
    )
    return parser


SUBCOMMANDS = {
    "export",
    "install",
    "remove",
    "enable",
    "disable",
    "pause",
    "resume",
    "restart",
    "status",
    "list",
    "retag",
    "stub-dates",
    "nightly",
}


def main(argv):
    argv = list(argv)
    if argv and argv[0] in ("-h", "--help"):
        build_parser().print_help()  # every subcommand (finding 21a)
        return 0
    if not argv or argv[0] not in SUBCOMMANDS:
        argv = ["export"] + argv
    args = build_parser().parse_args(argv)

    if args.cmd == "export":
        cfg, config_path = load_config(args.config)
        args.dest = args.dest or cfg.dest
        args.page = args.page or cfg.page
        args.log_interval = args.log_interval or cfg.log_interval
        signal.signal(signal.SIGINT, _sigint_handler)
        signal.signal(signal.SIGTERM, _sigterm_handler)
        return export_run(args, cfg, config_path)
    if args.cmd == "list":
        catalogue_table(fetch_catalogues())
        return 0
    if args.cmd == "install":
        return cmd_install(args)
    if args.cmd == "remove":
        return cmd_remove(args)
    if args.cmd == "enable":
        return cmd_enable_disable(args, True)
    if args.cmd == "disable":
        return cmd_enable_disable(args, False)
    if args.cmd == "pause":
        return cmd_pause(args)
    if args.cmd in ("resume", "restart"):
        return cmd_resume(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "retag":
        return cmd_retag(args)
    if args.cmd == "stub-dates":
        return cmd_stub_dates(args)
    if args.cmd == "nightly":
        return cmd_nightly(args)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
