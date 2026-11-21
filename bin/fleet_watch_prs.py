#!/usr/bin/env python3
"""Watch open pull requests we wait on; ping Hermes on news. No model, stdlib only.

  fleet-watch prs [--state-dir D] add OWNER/REPO N [N...]
  fleet-watch prs [--state-dir D] rm  OWNER/REPO N [N...]
  fleet-watch prs [--state-dir D] ls
  fleet-watch prs [--state-dir D] check [--dry-run]

The watch list and per-PR state are one JSON file, <state-dir>/prs.json (written
atomically). One GraphQL query per repo batches that repo's active PRs. Events that
ping, one ping per PR per run (`prs: <PR URL> <event; event>`): a new issue comment, a
new review, CI turning FAILURE/ERROR on the current head (once per head sha and failed
check set), and merged / closed without merge (after which the PR is inactive and no
longer fetched). Events by the authenticated user are left out; bots count. The first
time a PR is seen is a silent baseline. Pings never carry comment or review text:
third-party text stays out of Hermes (F-CRIT-1, the paused upstream watcher).

Environment: FLEET_WATCH_GH (gh binary), FLEET_WATCH_GH_TIMEOUT, FLEET_WATCH_PRS_SELF
(our login, else `gh api user`), HERMES_BIN / HERMES_PING_TARGET (as fleet-watch's notify()
passes them; else FLEET_WATCH_HERMES / FLEET_WATCH_TO / bin/inbox-target / the default).
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SLUG = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')
UNSAFE = re.compile(r'[^A-Za-z0-9 ._:/#@+-]')
FAIL_FAILS_AFTER = 6
SEEN_CAP = 300
CI_CAP = 50
FAILED_CONCLUSIONS = {'FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'CANCELLED'}
FAILED_STATES = {'FAILURE', 'ERROR'}
DEFAULT_TARGET = 'telegram:838808636:44130'

QUERY_HEAD = 'query($owner:String!, $repo:String!) { repository(owner:$owner, name:$repo) {\n'
QUERY_PR = '''  p%(n)d: pullRequest(number:%(n)d) {
    state merged url headRefOid
    comments(last:30) { nodes { id createdAt author { login } } }
    reviews(last:30) { nodes { id state submittedAt author { login } } }
    statusCheckRollup { state contexts(first:50) { nodes { __typename
      ... on CheckRun { name conclusion } ... on StatusContext { context state } } } }
  }
'''
QUERY_TAIL = '} }\n'


def clean(text):
    """Allow-list a third-party string for a ping: only [A-Za-z0-9 ._:/#@+-], 60 chars."""
    text = str(text if text is not None else '').replace('[bot]', ' bot')
    return UNSAFE.sub('', text)[:60].strip()


def log_line(state_dir, text):
    try:
        with open(os.path.join(state_dir, 'fleet-watch.log'), 'a') as stream:
            stream.write('%s prs: %s\n' % (dt.datetime.now().strftime('%F %T'), text))
    except OSError:
        pass


def atomic_write(path, data):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=str(path.parent), delete=False) as stream:
        os.chmod(stream.name, 0o600)
        json.dump(data, stream, indent=1, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, str(path))


class Watcher:
    def __init__(self, state_dir, dry=False, quiet=False):
        self.dir = Path(state_dir)
        self.path = self.dir / 'prs.json'
        self.dry = dry
        self.quiet = quiet
        self.gh_bin = os.environ.get('FLEET_WATCH_GH') or shutil.which('gh', path=os.environ.get('PATH', '') + ':/opt/homebrew/bin') or 'gh'
        self.timeout = int(os.environ.get('FLEET_WATCH_GH_TIMEOUT') or 30)

    # ---- state -------------------------------------------------------
    def load(self):
        if not self.path.exists():
            return {'version': 1, 'prs': {}, 'fetch': {}}
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('prs'), dict):
            raise ValueError('malformed %s' % self.path)
        data.setdefault('fetch', {})
        return data

    def save(self, state):
        if not self.dry:
            atomic_write(self.path, state)

    def locked(self):
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = open(str(self.dir / 'prs.lock'), 'a')
        fcntl.flock(lock, fcntl.LOCK_EX)
        return lock

    def info(self, text):
        if not self.quiet:
            print('prs: ' + text)

    # ---- gh and hermes -----------------------------------------------
    def gh(self, args):
        return subprocess.run([self.gh_bin] + args, capture_output=True, text=True, timeout=self.timeout)

    def whoami(self, state):
        env = os.environ.get('FLEET_WATCH_PRS_SELF')
        if env:
            return env
        if state.get('self'):
            return state['self']
        r = self.gh(['api', 'user', '--jq', '.login'])
        login = r.stdout.strip()
        if r.returncode != 0 or not re.fullmatch(r'[A-Za-z0-9-]{1,39}', login):
            raise ValueError('cannot resolve our GitHub login (gh api user rc=%s)' % r.returncode)
        state['self'] = login
        return login

    def ping(self, message):
        """Send through hermes-ping the way fleet-watch's notify() does. True on success."""
        if self.dry:
            self.info('DRY-RUN would ping: ' + message)
            return True
        env = dict(os.environ)
        if not env.get('HERMES_BIN'):
            env['HERMES_BIN'] = os.environ.get('FLEET_WATCH_HERMES') or str(Path.home() / '.local/bin/hermes')
        if not env.get('HERMES_PING_TARGET'):
            target = os.environ.get('FLEET_WATCH_TO', '')
            if not target:
                try:
                    inbox = Path(__file__).resolve().parent / 'inbox-target'
                    target = subprocess.run([str(inbox), 'fleet-watch'], capture_output=True, text=True, timeout=5).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    target = ''
            env['HERMES_PING_TARGET'] = target or DEFAULT_TARGET
        try:
            r = subprocess.run([str(Path.home() / '.local/bin/hermes-ping'), message], env=env,
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as error:
            log_line(self.dir, 'hermes-ping FAILED (%s) for: %s' % (type(error).__name__, message))
            return False
        if r.returncode != 0:
            log_line(self.dir, 'hermes-ping FAILED rc=%d for: %s' % (r.returncode, message))
            return False
        return True

    # ---- fetch -------------------------------------------------------
    def fetch_repo(self, repo, numbers):
        """One GraphQL call for the repo. Returns {number: pr-dict or None}; raises on a failed call."""
        owner, name = repo.split('/')
        query = QUERY_HEAD + ''.join(QUERY_PR % {'n': n} for n in numbers) + QUERY_TAIL
        r = self.gh(['api', 'graphql', '-f', 'query=' + query, '-f', 'owner=' + owner, '-f', 'repo=' + name])
        try:
            body = json.loads(r.stdout)
            repository = body['data']['repository']
        except (ValueError, KeyError, TypeError):
            raise ValueError('graphql failed rc=%d: %s' % (r.returncode, clean(r.stderr or r.stdout)))
        if not isinstance(repository, dict):
            raise ValueError('graphql returned no repository')
        return {n: repository.get('p%d' % n) for n in numbers}

    # ---- one PR ------------------------------------------------------
    @staticmethod
    def login(node):
        author = node.get('author') if isinstance(node, dict) else None
        return (author or {}).get('login') or 'ghost'

    @staticmethod
    def failed_checks(pr):
        rollup = pr.get('statusCheckRollup') or {}
        if rollup.get('state') not in FAILED_STATES:
            return None
        names = set()
        for node in ((rollup.get('contexts') or {}).get('nodes')) or []:
            if node.get('__typename') == 'CheckRun' and node.get('conclusion') in FAILED_CONCLUSIONS:
                names.add(clean(node.get('name')))
            elif node.get('__typename') == 'StatusContext' and node.get('state') in FAILED_STATES:
                names.add(clean(node.get('context')))
        names.discard('')
        return sorted(names) or ['unknown check']

    def examine(self, entry, pr, me):
        """Return (events, delta) for a fetched PR; delta is applied to the entry after a ping."""
        comments = [n for n in ((pr.get('comments') or {}).get('nodes')) or [] if n]
        reviews = [n for n in ((pr.get('reviews') or {}).get('nodes')) or [] if n and n.get('state') != 'PENDING']
        sha = str(pr.get('headRefOid') or '')[:40]
        failed = self.failed_checks(pr) if pr.get('state') == 'OPEN' else None
        ci_key = '%s:%s' % (sha, ','.join(failed)) if failed else None
        delta = {'comments': [c['id'] for c in comments], 'reviews': [r['id'] for r in reviews],
                 'ci': ci_key, 'closed': pr.get('state') in ('MERGED', 'CLOSED')}
        if not entry.get('baselined'):
            return None, delta
        events = []
        mine = me.lower()
        seen_c, seen_r = set(entry.get('seen_comments', [])), set(entry.get('seen_reviews', []))
        authors = []
        for c in comments:
            who = self.login(c)
            if c['id'] not in seen_c and who.lower() != mine and clean(who) not in authors:
                authors.append(clean(who))
        total = len([c for c in comments if c['id'] not in seen_c and self.login(c).lower() != mine])
        if total:
            events.append('%d comment%s by %s' % (total, '' if total == 1 else 's', ', '.join(authors[:5])))
        for r in reviews:
            who = self.login(r)
            if r['id'] not in seen_r and who.lower() != mine:
                events.append('review %s by %s' % (clean(r.get('state')), clean(who)))
        if ci_key and ci_key not in entry.get('ci_pinged', []):
            names = failed[:5] + (['+%d more' % (len(failed) - 5)] if len(failed) > 5 else [])
            events.append('CI failing on %s: %s' % (sha[:7], ', '.join(names)))
        if pr.get('merged') or pr.get('state') == 'MERGED':
            events.append('merged')
        elif pr.get('state') == 'CLOSED':
            events.append('closed without merge')
        return events, delta

    @staticmethod
    def apply(entry, delta):
        for key, ids in (('seen_comments', delta['comments']), ('seen_reviews', delta['reviews'])):
            merged = list(entry.get(key, []))
            merged += [i for i in ids if i not in merged]
            entry[key] = merged[-SEEN_CAP:]
        if delta['ci']:
            pinged = list(entry.get('ci_pinged', []))
            if delta['ci'] not in pinged:
                pinged.append(delta['ci'])
            entry['ci_pinged'] = pinged[-CI_CAP:]
        entry['baselined'] = True
        if delta['closed']:
            entry['active'] = False

    # ---- run ---------------------------------------------------------
    def run(self):
        if not self.dry:
            with self.locked():
                return self.check()
        return self.check()

    def check(self):
        state = self.load()
        groups = {}
        for key, entry in sorted(state['prs'].items()):
            if entry.get('active', True):
                groups.setdefault(entry['repo'], []).append(entry['number'])
        if not groups:
            self.info('no active PRs')
            return 0
        me = self.whoami(state)
        errors = 0
        for repo, numbers in sorted(groups.items()):
            fetch = state['fetch'].setdefault(repo, {'fails': 0, 'alerted': False})
            failed = None
            prs = {}
            try:
                prs = self.fetch_repo(repo, numbers)
                missing = [n for n, pr in prs.items() if not isinstance(pr, dict)]
                if missing:
                    # A missing alias counts as the repo's fetch failure, but the PRs that did come back are still processed.
                    failed = 'ValueError: PR(s) not found: %s' % ','.join('#%d' % n for n in missing)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failed = '%s: %s' % (type(error).__name__, error)
                prs = {}
            if failed:
                errors += 1
                fetch['fails'] += 1
                log_line(self.dir, 'fetch failed for %s (%d in a row): %s' % (repo, fetch['fails'], failed))
                print('prs: fetch failed for %s (%d in a row): %s' % (repo, fetch['fails'], failed), file=sys.stderr)
                if fetch['fails'] >= FAIL_FAILS_AFTER and not fetch['alerted'] and self.ping('prs: fetch failing for ' + repo):
                    fetch['alerted'] = True
            elif fetch['fails']:
                if not fetch['alerted'] or self.ping('prs: fetch recovered for ' + repo):
                    fetch['fails'], fetch['alerted'] = 0, False
            # Good aliases are processed even when a sibling alias was missing.
            for number in numbers:
                pr = prs.get(number)
                if isinstance(pr, dict):
                    self.one(state, repo, number, pr, me)
            self.save(state)
        return 1 if errors else 0

    def one(self, state, repo, number, pr, me):
        key = '%s#%d' % (repo, number)
        entry = state['prs'][key]
        url = 'https://github.com/%s/pull/%d' % (repo, number)
        events, delta = self.examine(entry, pr, me)
        if events is None:
            self.info('%s baseline recorded%s (silent)' % (url, ', already ' + pr['state'].lower() if delta['closed'] else ''))
            if not self.dry:
                self.apply(entry, delta)
            return
        if not events:
            self.info('%s no news' % url)
            if not self.dry:
                self.apply(entry, delta)
            return
        message = ('prs: %s %s' % (url, '; '.join(events)))[:400]
        if self.ping(message):
            if not self.dry:
                self.apply(entry, delta)
        else:
            print('prs: ping failed for %s; will retry next run' % url, file=sys.stderr)


# ---- list management ---------------------------------------------------
def parse_target(repo, numbers):
    if not SLUG.match(repo):
        raise ValueError('repo must be OWNER/REPO, got %r' % repo)
    out = []
    for text in numbers:
        if not re.fullmatch(r'[1-9][0-9]{0,8}', text):
            raise ValueError('PR number must be a positive integer, got %r' % text)
        out.append(int(text))
    return out


def command_add(watcher, repo, numbers):
    nums = parse_target(repo, numbers)
    with watcher.locked():
        state = watcher.load()
        for n in nums:
            key = '%s#%d' % (repo, n)
            old = state['prs'].get(key)
            if old and old.get('active', True):
                print('prs: %s already watched' % key)
                continue
            state['prs'][key] = {'repo': repo, 'number': n, 'active': True, 'baselined': False,
                                 'seen_comments': [], 'seen_reviews': [], 'ci_pinged': []}
            print('prs: watching %s (baseline on the next check)' % key)
        watcher.save(state)
    return 0


def command_rm(watcher, repo, numbers):
    nums = parse_target(repo, numbers)
    with watcher.locked():
        state = watcher.load()
        for n in nums:
            key = '%s#%d' % (repo, n)
            if state['prs'].pop(key, None) is None:
                print('prs: %s was not watched' % key)
            else:
                print('prs: removed %s' % key)
        if not any(e['repo'] == repo for e in state['prs'].values()):
            state['fetch'].pop(repo, None)
        watcher.save(state)
    return 0


def command_ls(watcher):
    state = watcher.load()
    if not state['prs']:
        print('prs: nothing watched')
    for key, entry in sorted(state['prs'].items()):
        print('%s %s %s' % (key, 'active' if entry.get('active', True) else 'inactive',
                            'baselined' if entry.get('baselined') else 'new'))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--state-dir', default=os.path.join(os.environ.get('HOME', str(Path.home())), '.local/state/fleet-watch'))
    parser.add_argument('--scheduled', action='store_true', help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='cmd')
    for name in ('add', 'rm'):
        p = sub.add_parser(name)
        p.add_argument('repo')
        p.add_argument('numbers', nargs='+')
    sub.add_parser('ls')
    check = sub.add_parser('check')
    check.add_argument('--dry-run', action='store_true', help='read GitHub, print would-be pings, write and send nothing')
    args = parser.parse_args(argv)
    cmd = args.cmd or 'check'
    watcher = Watcher(args.state_dir, dry=getattr(args, 'dry_run', False), quiet=args.scheduled)
    try:
        if cmd == 'add':
            return command_add(watcher, args.repo, args.numbers)
        if cmd == 'rm':
            return command_rm(watcher, args.repo, args.numbers)
        if cmd == 'ls':
            return command_ls(watcher)
        return watcher.run()
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print('prs: %s: %s' % (type(error).__name__, error), file=sys.stderr)
        log_line(args.state_dir, 'run failed: %s: %s' % (type(error).__name__, error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
