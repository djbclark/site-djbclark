#!/usr/bin/env python3
"""Watch the pull requests, issues and security advisories we wait on; ping Hermes on news.
No model, stdlib only.

  fleet-watch prs        [--state-dir D] add|rm OWNER/REPO N [N...]      (also: ls)
  fleet-watch issues     [--state-dir D] add|rm OWNER/REPO N [N...]      (also: ls)
  fleet-watch advisories [--state-dir D] add|rm OWNER/REPO GHSA-xxxx-xxxx-xxxx   (also: ls)
  fleet-watch prs|issues|advisories [--state-dir D] check [--dry-run]    (check covers all three kinds)

The watch list and per-item state are one JSON file, <state-dir>/prs.json (written atomically;
the `issues` and `advisories` keys are added on first use, so a file from before them loads as
it is). One GraphQL query per repo batches that repo's active PRs and issues together.
Events that ping, one ping per item per run:
  prs: <PR URL> <event; event>   a new issue comment, a new review, CI turning FAILURE/ERROR on
      the current head (once per head sha and failed check set), merged / closed without merge
  issues: <issue URL> <event; event>   new comments, closed (as completed / not planned /
      duplicate), reopened
  advisory: <advisory URL> <event; event>   state change, CVE assigned, published, closed,
      collaborator count change, new comment count, or a bare "updated"
A merged / closed PR, a closed issue, and a published / closed advisory pings once and goes
inactive (no longer fetched). Events by the authenticated user are left out; bots count. The
first time an item is seen is a silent baseline. Pings never carry titles, bodies, summaries,
descriptions or comment text: third-party text stays out of Hermes (F-CRIT-1, the paused
upstream watcher), and a private advisory's text never leaves GitHub.

Advisories are fetched with REST `GET repos/OWNER/REPO/security-advisories/GHSA` (one call per
advisory per run; a private one needs access to it, a 403/404 is a fetch failure like any
other). The API exposes no advisory comment thread, only an undocumented integer `comments`
count (tracked when present), so "updated" means: look at the advisory page. The advisory URL
is built, never taken from the response, and the GHSA id is checked against the GitHub format
before any URL is built.

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
GHSA = re.compile(r'GHSA(-[23456789cfghjmpqrvwx]{4}){3}\Z')
CVE = re.compile(r'CVE-[0-9]{4}-[0-9]{4,19}\Z')
DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
UNSAFE = re.compile(r'[^A-Za-z0-9 ._:/#@+-]')
FAIL_FAILS_AFTER = 6
SEEN_CAP = 300
CI_CAP = 50
FAILED_CONCLUSIONS = {'FAILURE', 'TIMED_OUT', 'STARTUP_FAILURE', 'CANCELLED'}
FAILED_STATES = {'FAILURE', 'ERROR'}
CLOSE_REASONS = {'COMPLETED': 'completed', 'NOT_PLANNED': 'not planned', 'DUPLICATE': 'duplicate'}
DONE_ADVISORY_STATES = ('published', 'closed')
DEFAULT_TARGET = 'telegram:838808636:44130'
KINDS = ('prs', 'issues', 'advisories')
LABEL = {'prs': 'prs', 'issues': 'issues', 'advisories': 'advisory'}

QUERY_HEAD = 'query($owner:String!, $repo:String!) { repository(owner:$owner, name:$repo) {\n'
QUERY_PR = '''  p%(n)d: pullRequest(number:%(n)d) {
    state merged url headRefOid
    comments(last:30) { nodes { id createdAt author { login } } }
    reviews(last:30) { nodes { id state submittedAt author { login } } }
    statusCheckRollup { state contexts(first:50) { nodes { __typename
      ... on CheckRun { name conclusion } ... on StatusContext { context state } } } }
  }
'''
QUERY_ISSUE = '''  i%(n)d: issue(number:%(n)d) {
    state stateReason url
    comments(last:30) { nodes { id createdAt author { login } } }
    timelineItems(last:10, itemTypes:[REOPENED_EVENT]) { nodes { __typename ... on ReopenedEvent { id } } }
  }
'''
QUERY_KIND = '  x%(n)d: issueOrPullRequest(number:%(n)d) { __typename }\n'
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
            return {'version': 1, 'prs': {}, 'issues': {}, 'advisories': {}, 'fetch': {}}
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict) or not isinstance(data.get('prs'), dict):
            raise ValueError('malformed %s' % self.path)
        for kind in ('issues', 'advisories'):
            if not isinstance(data.setdefault(kind, {}), dict):
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

    def info(self, text, kind='prs'):
        if not self.quiet:
            print('%s: %s' % (LABEL[kind], text))

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
    def graphql_repository(self, repo, body):
        """Run one repository query; returns the repository dict, raises ValueError otherwise."""
        owner, name = repo.split('/')
        r = self.gh(['api', 'graphql', '-f', 'query=' + QUERY_HEAD + body + QUERY_TAIL,
                     '-f', 'owner=' + owner, '-f', 'repo=' + name])
        try:
            repository = json.loads(r.stdout)['data']['repository']
        except (ValueError, KeyError, TypeError):
            raise ValueError('graphql failed rc=%d: %s' % (r.returncode, clean(r.stderr or r.stdout)))
        if not isinstance(repository, dict):
            raise ValueError('graphql returned no repository')
        return repository

    def fetch_repo(self, repo, pr_numbers, issue_numbers=()):
        """One GraphQL call for the repo. Returns ({number: pr}, {number: issue}), a value None when
        missing; raises on a failed call."""
        body = ''.join(QUERY_PR % {'n': n} for n in pr_numbers) + ''.join(QUERY_ISSUE % {'n': n} for n in issue_numbers)
        repository = self.graphql_repository(repo, body)
        return ({n: repository.get('p%d' % n) for n in pr_numbers},
                {n: repository.get('i%d' % n) for n in issue_numbers})

    def fetch_advisory(self, repo, ghsa):
        """REST GET of one repository security advisory; returns the snapshot of the fields we track.
        Error text never includes the response body (a private advisory's text stays out of logs)."""
        r = self.gh(['api', 'repos/%s/security-advisories/%s' % (repo, ghsa)])
        if r.returncode != 0:
            code = re.search(r'HTTP ([0-9]{3})', r.stderr or '')
            raise ValueError('advisory fetch failed: %s' % ('HTTP ' + code.group(1) if code else 'gh rc=%d' % r.returncode))
        try:
            advisory = json.loads(r.stdout)
        except ValueError:
            raise ValueError('advisory response is not JSON')
        if not isinstance(advisory, dict) or not isinstance(advisory.get('state'), str):
            raise ValueError('advisory response has no state')
        return self.advisory_snapshot(advisory)

    # ---- one PR ------------------------------------------------------
    @staticmethod
    def login(node):
        author = node.get('author') if isinstance(node, dict) else None
        return (author or {}).get('login') or 'ghost'

    def comment_event(self, comments, seen, me):
        """'N comments by a, b' for comments not seen and not ours, else None."""
        mine = me.lower()
        authors = []
        for c in comments:
            who = self.login(c)
            if c['id'] not in seen and who.lower() != mine and clean(who) not in authors:
                authors.append(clean(who))
        total = len([c for c in comments if c['id'] not in seen and self.login(c).lower() != mine])
        if not total:
            return None
        return '%d comment%s by %s' % (total, '' if total == 1 else 's', ', '.join(authors[:5]))

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
        seen_r = set(entry.get('seen_reviews', []))
        said = self.comment_event(comments, set(entry.get('seen_comments', [])), me)
        if said:
            events.append(said)
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

    def examine_issue(self, entry, issue, me):
        """Return (events, delta) for a fetched issue (same shape as examine)."""
        comments = [n for n in ((issue.get('comments') or {}).get('nodes')) or [] if n]
        reopens = [n['id'] for n in ((issue.get('timelineItems') or {}).get('nodes')) or [] if n and n.get('id')]
        closed = issue.get('state') == 'CLOSED'
        delta = {'comments': [c['id'] for c in comments], 'reopens': reopens, 'closed': closed}
        if not entry.get('baselined'):
            return None, delta
        events = []
        said = self.comment_event(comments, set(entry.get('seen_comments', [])), me)
        if said:
            events.append(said)
        if [i for i in reopens if i not in entry.get('seen_reopens', [])]:
            events.append('reopened')
        if closed:
            reason = CLOSE_REASONS.get(issue.get('stateReason'))
            events.append('closed as ' + reason if reason else 'closed')
        return events, delta

    # ---- one advisory --------------------------------------------------
    @staticmethod
    def advisory_snapshot(advisory):
        def count(value):
            return len(value) if isinstance(value, list) else 0

        def stamp(value):
            return str(value)[:40] if value else None

        cve = advisory.get('cve_id')
        comments = advisory.get('comments')
        return {
            'state': clean(advisory.get('state')),
            'updated_at': stamp(advisory.get('updated_at')),
            'published_at': stamp(advisory.get('published_at')),
            'closed_at': stamp(advisory.get('closed_at')),
            'cve': (cve if isinstance(cve, str) and CVE.match(cve) else '?') if cve else None,
            'users': count(advisory.get('collaborating_users')),
            'teams': count(advisory.get('collaborating_teams')),
            'comments': comments if isinstance(comments, int) and not isinstance(comments, bool) else None,
        }

    @staticmethod
    def advisory_done(snap):
        return snap['state'] in DONE_ADVISORY_STATES or bool(snap['published_at'] or snap['closed_at'])

    def examine_advisory(self, entry, snap):
        """Return (events, delta) for a fetched advisory; delta is the new snapshot."""
        if not entry.get('baselined'):
            return None, snap
        old = entry.get('snap') or {}
        events = []
        if snap['state'] != old.get('state'):
            if snap['state'] in DONE_ADVISORY_STATES:
                events.append(snap['state'])
            else:
                events.append('state %s to %s' % (old.get('state') or '?', snap['state'] or '?'))
        elif snap['published_at'] and not old.get('published_at'):
            events.append('published')
        elif snap['closed_at'] and not old.get('closed_at'):
            events.append('closed')
        if snap['cve'] != old.get('cve'):
            if snap['cve'] and not old.get('cve'):
                events.append('CVE assigned ' + snap['cve'])
            elif snap['cve']:
                events.append('CVE changed to ' + snap['cve'])
            else:
                events.append('CVE removed')
        for field, word in (('users', 'users'), ('teams', 'teams')):
            if snap[field] != old.get(field):
                events.append('collaborating %s %s to %d' % (word, old.get(field, '?'), snap[field]))
        if snap['comments'] is not None and old.get('comments') is not None and snap['comments'] > old['comments']:
            events.append('%d new comment%s' % (snap['comments'] - old['comments'], '' if snap['comments'] - old['comments'] == 1 else 's'))
        if not events and snap['updated_at'] != old.get('updated_at'):
            day = (snap['updated_at'] or '')[:10]
            events.append('updated%s, see the advisory page' % (' ' + day if DATE.match(day) else ''))
        return events, snap

    @staticmethod
    def apply_advisory(entry, snap):
        entry['snap'] = snap
        entry['baselined'] = True
        if Watcher.advisory_done(snap):
            entry['active'] = False

    @staticmethod
    def apply(entry, delta):
        for key, ids in (('seen_comments', delta.get('comments')), ('seen_reviews', delta.get('reviews')),
                         ('seen_reopens', delta.get('reopens'))):
            if ids is None:
                continue
            merged = list(entry.get(key, []))
            merged += [i for i in ids if i not in merged]
            entry[key] = merged[-SEEN_CAP:]
        if delta.get('ci'):
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

    def account(self, state, key, failed, label, subject):
        """Count a fetch failure (or recovery) for `key`; ping after FAIL_FAILS_AFTER in a row, once.
        Returns 1 for a failure."""
        fetch = state['fetch'].setdefault(key, {'fails': 0, 'alerted': False})
        if failed:
            fetch['fails'] += 1
            log_line(self.dir, 'fetch failed for %s (%d in a row): %s' % (subject, fetch['fails'], failed))
            print('%s: fetch failed for %s (%d in a row): %s' % (label, subject, fetch['fails'], failed), file=sys.stderr)
            if fetch['fails'] >= FAIL_FAILS_AFTER and not fetch['alerted'] and self.ping('%s: fetch failing for %s' % (label, subject)):
                fetch['alerted'] = True
            return 1
        if fetch['fails']:
            if not fetch['alerted'] or self.ping('%s: fetch recovered for %s' % (label, subject)):
                fetch['fails'], fetch['alerted'] = 0, False
        return 0

    def check(self):
        state = self.load()
        groups = {}
        for kind in ('prs', 'issues'):
            for key, entry in sorted(state[kind].items()):
                if entry.get('active', True):
                    groups.setdefault(entry['repo'], {'prs': [], 'issues': []})[kind].append(entry['number'])
        advisories = [(k, e) for k, e in sorted(state['advisories'].items()) if e.get('active', True)]
        if not groups and not advisories:
            self.info('nothing active to check')
            return 0
        me = self.whoami(state) if groups else ''
        errors = 0
        for repo, group in sorted(groups.items()):
            failed = None
            prs, issues = {}, {}
            try:
                prs, issues = self.fetch_repo(repo, group['prs'], group['issues'])
                missing = []
                if [n for n, pr in prs.items() if not isinstance(pr, dict)]:
                    missing.append('PR(s) not found: %s' % ','.join('#%d' % n for n, pr in prs.items() if not isinstance(pr, dict)))
                if [n for n, item in issues.items() if not isinstance(item, dict)]:
                    missing.append('issue(s) not found: %s' % ','.join('#%d' % n for n, item in issues.items() if not isinstance(item, dict)))
                if missing:
                    # A missing alias counts as the repo's fetch failure, but the items that did come back are still processed.
                    failed = 'ValueError: ' + '; '.join(missing)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failed = '%s: %s' % (type(error).__name__, error)
                prs, issues = {}, {}
            errors += self.account(state, repo, failed, 'prs' if group['prs'] else 'issues', repo)
            # Good aliases are processed even when a sibling alias was missing.
            for number in group['prs']:
                pr = prs.get(number)
                if isinstance(pr, dict):
                    self.one(state, repo, number, pr, me)
            for number in group['issues']:
                issue = issues.get(number)
                if isinstance(issue, dict):
                    self.one_issue(state, repo, number, issue, me)
            self.save(state)
        for key, entry in advisories:
            repo, ghsa = entry['repo'], entry['ghsa']
            failed, snap = None, None
            try:
                if not SLUG.match(repo) or not GHSA.match(ghsa):
                    raise ValueError('bad advisory entry in the state file')
                snap = self.fetch_advisory(repo, ghsa)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failed = '%s: %s' % (type(error).__name__, error if isinstance(error, ValueError) else '')
            errors += self.account(state, 'advisory:' + key, failed, 'advisory', '%s %s' % (repo, ghsa))
            if snap is not None:
                self.one_advisory(entry, repo, ghsa, snap)
        self.save(state)
        return 1 if errors else 0

    def deliver(self, kind, url, entry, events, delta, apply, note=''):
        """Baseline silently, or ping the events and advance the entry only after the ping succeeds."""
        if events is None:
            self.info('%s baseline recorded%s (silent)' % (url, note), kind)
            if not self.dry:
                apply(entry, delta)
            return
        if not events:
            self.info('%s no news' % url, kind)
            if not self.dry:
                apply(entry, delta)
            return
        message = ('%s: %s %s' % (LABEL[kind], url, '; '.join(events)))[:400]
        if self.ping(message):
            if not self.dry:
                apply(entry, delta)
        else:
            print('%s: ping failed for %s; will retry next run' % (LABEL[kind], url), file=sys.stderr)

    def one(self, state, repo, number, pr, me):
        entry = state['prs']['%s#%d' % (repo, number)]
        url = 'https://github.com/%s/pull/%d' % (repo, number)
        events, delta = self.examine(entry, pr, me)
        note = ', already ' + clean(pr.get('state')).lower() if delta['closed'] else ''
        self.deliver('prs', url, entry, events, delta, self.apply, note)

    def one_issue(self, state, repo, number, issue, me):
        entry = state['issues']['%s#%d' % (repo, number)]
        url = 'https://github.com/%s/issues/%d' % (repo, number)
        events, delta = self.examine_issue(entry, issue, me)
        note = ', already closed' if delta['closed'] else ''
        self.deliver('issues', url, entry, events, delta, self.apply, note)

    def one_advisory(self, entry, repo, ghsa, snap):
        url = 'https://github.com/%s/security/advisories/%s' % (repo, ghsa)
        events, delta = self.examine_advisory(entry, snap)
        note = ', already ' + snap['state'] if self.advisory_done(snap) else ''
        self.deliver('advisories', url, entry, events, delta, self.apply_advisory, note)

    # ---- add-time kind check ------------------------------------------
    def verify_kind(self, repo, numbers, want):
        """Refuse numbers that do not exist or are the other kind (an issue for `prs add`, a PR for
        `issues add`). One GraphQL call; raises ValueError with a clear message."""
        try:
            repository = self.graphql_repository(repo, ''.join(QUERY_KIND % {'n': n} for n in numbers))
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError('cannot check %s with GitHub (%s)' % (repo, type(error).__name__))
        problems = []
        for n in numbers:
            node = repository.get('x%d' % n)
            found = node.get('__typename') if isinstance(node, dict) else None
            if found is None:
                problems.append('%s#%d does not exist' % (repo, n))
            elif found != want:
                other = 'a pull request' if found == 'PullRequest' else 'an issue'
                problems.append('%s#%d is %s, not %s; use `fleet-watch %s add`' % (
                    repo, n, other, 'a pull request' if want == 'PullRequest' else 'an issue',
                    'prs' if found == 'PullRequest' else 'issues'))
        if problems:
            raise ValueError('; '.join(problems))


# ---- list management ---------------------------------------------------
def parse_targets(kind, repo, targets):
    if not SLUG.match(repo):
        raise ValueError('repo must be OWNER/REPO, got %r' % repo)
    out = []
    for text in targets:
        if kind == 'advisories':
            if not GHSA.match(text):
                raise ValueError('advisory id must look like GHSA-xxxx-xxxx-xxxx, got %r' % clean(text))
            out.append(text)
        else:
            if not re.fullmatch(r'[1-9][0-9]{0,8}', text):
                raise ValueError('%s number must be a positive integer, got %r' % ('PR' if kind == 'prs' else 'issue', clean(text)))
            out.append(int(text))
    return out


def item_key(repo, target):
    return '%s#%s' % (repo, target)


def new_entry(kind, repo, target):
    if kind == 'prs':
        return {'repo': repo, 'number': target, 'active': True, 'baselined': False,
                'seen_comments': [], 'seen_reviews': [], 'ci_pinged': []}
    if kind == 'issues':
        return {'repo': repo, 'number': target, 'active': True, 'baselined': False,
                'seen_comments': [], 'seen_reopens': []}
    return {'repo': repo, 'ghsa': target, 'active': True, 'baselined': False}


def command_add(watcher, kind, repo, targets):
    items = parse_targets(kind, repo, targets)
    label = LABEL[kind]
    with watcher.locked():
        state = watcher.load()
        todo = []
        for target in items:
            old = state[kind].get(item_key(repo, target))
            if old and old.get('active', True):
                print('%s: %s already watched' % (label, item_key(repo, target)))
            elif target not in todo:
                todo.append(target)
        if kind != 'advisories' and todo:
            watcher.verify_kind(repo, todo, 'PullRequest' if kind == 'prs' else 'Issue')
        for target in todo:
            state[kind][item_key(repo, target)] = new_entry(kind, repo, target)
            print('%s: watching %s (baseline on the next check)' % (label, item_key(repo, target)))
        watcher.save(state)
    return 0


def command_rm(watcher, kind, repo, targets):
    items = parse_targets(kind, repo, targets)
    label = LABEL[kind]
    with watcher.locked():
        state = watcher.load()
        for target in items:
            key = item_key(repo, target)
            if state[kind].pop(key, None) is None:
                print('%s: %s was not watched' % (label, key))
            else:
                print('%s: removed %s' % (label, key))
            if kind == 'advisories':
                state['fetch'].pop('advisory:' + key, None)
        if not any(e['repo'] == repo for k in ('prs', 'issues') for e in state[k].values()):
            state['fetch'].pop(repo, None)
        watcher.save(state)
    return 0


def command_ls(watcher, kind):
    state = watcher.load()
    if not state[kind]:
        print('%s: nothing watched' % LABEL[kind])
    for key, entry in sorted(state[kind].items()):
        print('%s %s %s' % (key, 'active' if entry.get('active', True) else 'inactive',
                            'baselined' if entry.get('baselined') else 'new'))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--state-dir', default=os.path.join(os.environ.get('HOME', str(Path.home())), '.local/state/fleet-watch'))
    parser.add_argument('--kind', choices=KINDS, default='prs', help=argparse.SUPPRESS)
    parser.add_argument('--scheduled', action='store_true', help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest='cmd')
    for name in ('add', 'rm'):
        p = sub.add_parser(name)
        p.add_argument('repo')
        p.add_argument('targets', nargs='+', help='PR or issue numbers, or GHSA ids')
    sub.add_parser('ls')
    check = sub.add_parser('check')
    check.add_argument('--dry-run', action='store_true', help='read GitHub, print would-be pings, write and send nothing')
    args = parser.parse_args(argv)
    cmd = args.cmd or 'check'
    watcher = Watcher(args.state_dir, dry=getattr(args, 'dry_run', False), quiet=args.scheduled)
    try:
        if cmd == 'add':
            return command_add(watcher, args.kind, args.repo, args.targets)
        if cmd == 'rm':
            return command_rm(watcher, args.kind, args.repo, args.targets)
        if cmd == 'ls':
            return command_ls(watcher, args.kind)
        return watcher.run()
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print('%s: %s: %s' % (LABEL[args.kind], type(error).__name__, error), file=sys.stderr)
        log_line(args.state_dir, 'run failed: %s: %s' % (type(error).__name__, error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
