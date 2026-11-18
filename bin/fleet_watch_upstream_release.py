#!/usr/bin/env python3
"""Registry-driven upstream release alerts. No models; GitHub issues are append-only."""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

CENTRAL = 'djbclark/upstream-releases'
SLUG = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z')
TAG = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+/-]{0,180}\Z')
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9.+_-]{0,100}\Z')


def command(argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=30).stdout


def registry(path):
    try:
        data = json.loads(Path(path).read_text())
        assert type(data['schema_version']) is int and data['schema_version'] == 1
        assert isinstance(data['owners'], dict) and set(data['owners']) == {'djbclark', 'djbcsipb', 'frdminc'}
        assert isinstance(data['generated_at'], str) and data['generated_at'].endswith('Z')
        assert isinstance(data['components'], list)
        for owner, coverage in data['owners'].items():
            assert re.fullmatch(r'[A-Za-z0-9-]+', owner)
            assert type(coverage['complete']) is bool
            assert coverage['scope'] == 'credential-visible'
        pairs = set()
        for row in data['components']:
            assert isinstance(row['id'], str) and row['id']
            assert type(row['private']) is bool
            assert isinstance(row['catalog_ids'], list) and all(isinstance(c, str) for c in row['catalog_ids'])
            assert row['upstream'] == 'https://github.com/' + row['upstream_repo']
            assert row['fork'] == 'https://github.com/' + row['fork_repo']
            assert SLUG.fullmatch(row['upstream_repo']) and SLUG.fullmatch(row['fork_repo'])
            assert row['fork_repo'].split('/')[0] in data['owners']
            assert type(row['watch_releases']) is bool
            assert row['base_tag'] is None or TAG.fullmatch(row['base_tag'])
            assert row['upstream_repo'] not in pairs, 'ambiguous duplicate upstream'
            pairs.add(row['upstream_repo'])
            if row.get('installed_version') is not None:
                assert VERSION.fullmatch(row['installed_version'])
        return data
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
        raise ValueError('missing, malformed or unsupported registry (schema_version must be 1)') from error


def save(path, data):
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        os.chmod(stream.name, 0o600)
        json.dump(data, stream)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, path)


def stamp(now):
    return dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


class Watcher:
    def __init__(self, gh=None, clock=time.time, ping=None, installed=None):
        self.transport = gh or (lambda args: command(['gh', *args]))
        self.remaining = None
        self.calls = 0
        self.issue_cache = None
        self.label_cache = None
        self.clock = clock
        self.ping = ping or (lambda text: command([str(Path.home()/'.local/bin/hermes-ping'), text]))
        self.installed = installed or self.app_version

    @staticmethod
    def app_version(row):
        value = row.get('installed_version')
        if value is None and row['upstream_repo'].lower() == 'getpaseo/paseo':
            try:
                value = command(['plutil', '-extract', 'CFBundleShortVersionString', 'raw', '-o', '-',
                                 '/Applications/Paseo.app/Contents/Info.plist']).strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return value if isinstance(value, str) and VERSION.fullmatch(value) else 'n/a'

    def gh(self, args):
        if self.remaining is None:
            quota = json.loads(self.transport(['api', 'rate_limit']))
            self.remaining = quota['resources']['core']['remaining']
        if self.remaining <= 500 or self.calls >= 200:
            raise ValueError('GitHub budget held (500 reserve or 200-call run cap)')
        self.remaining -= 1
        self.calls += 1
        return self.transport(args)

    def api(self, path):
        rows = []
        for page in range(1, 201):
            batch = json.loads(self.gh(['api', path + ('&' if '?' in path else '?') + f'page={page}']))
            if not isinstance(batch, list):
                raise ValueError('invalid paginated GitHub response')
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise ValueError('pagination exceeds budget; no complete snapshot')

    def snapshot(self, repo, now):
        releases = self.api(f'repos/{repo}/releases?per_page=100')
        tags = self.api(f'repos/{repo}/tags?per_page=100')
        result = {}
        for row in tags:
            tag = row['name']
            if not TAG.fullmatch(tag):
                raise ValueError('unsafe tag in upstream response')
            result[tag] = {'published': None, 'beta': bool(re.search(r'-(beta|rc|alpha)(?:[.\d-]|$)', tag, re.I)),
                           'url': f'https://github.com/{repo}/releases/tag/{quote(tag, safe="")}' }
        for row in releases:
            if row.get('draft'):
                continue
            tag = row['tag_name']
            if not TAG.fullmatch(tag):
                raise ValueError('unsafe release tag')
            published = row['published_at']
            parsed = dt.datetime.fromisoformat(published.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('release timestamp lacks timezone')
            result[tag] = {'published': parsed.astimezone(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                           'beta': bool(row['prerelease']) or bool(re.search(r'-(beta|rc|alpha)(?:[.\d-]|$)', tag, re.I)),
                           'url': f'https://github.com/{repo}/releases/tag/{quote(tag, safe="")}' }
        return result

    def issue(self, row, tag, event, dry):
        repo = row['upstream_repo']
        if event['published'] is None:
            # Annotated tags carry their tagger date; lightweight tags expose only
            # the commit date (GitHub does not expose their publication time).
            ref = json.loads(self.gh(['api', f'repos/{repo}/git/ref/tags/{quote(tag, safe="")}']))
            if ref['object']['type'] == 'tag':
                obj = json.loads(self.gh(['api', f'repos/{repo}/git/tags/{ref["object"]["sha"]}']))
                published = obj['tagger']['date']
            else:
                commit = json.loads(self.gh(['api', f'repos/{repo}/commits/{quote(tag, safe="")}']))
                published = commit['commit']['committer']['date']
            date = dt.datetime.fromisoformat(published.replace('Z', '+00:00'))
            if date.tzinfo is None:
                raise ValueError('tag commit timestamp lacks timezone')
            event['published'] = date.astimezone(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        title = f'[radar][urgent] Upstream {repo} release {tag}'
        labels = ['radar', 'urgent', 'upstream-release', 'fork:' + row['fork_repo'].split('/')[1]]
        body = '\n'.join([
            f'Upstream: {repo}', f'Fork: {row["fork_repo"]}', f'Tag: {tag}',
            f'Release URL: {event["url"]}', f'Published (UTC): {event["published"]}',
            'Kind: ' + ('beta' if event['beta'] else 'stable'),
            'Our fork base tag: ' + (row['base_tag'] or 'unknown'),
            'Installed app version: ' + self.installed(row),
            'Action: review changelog; check whether our open upstream issues are fixed; fork needs rebase'])
        # List ALL states, never recreate closed alerts. Use complete paginated listing
        # instead of eventually-consistent search indexing after an uncertain create.
        if self.issue_cache is None:
            self.issue_cache = self.api(f'repos/{CENTRAL}/issues?state=all&per_page=100')
        issues = self.issue_cache
        for issue in issues:
            if issue.get('title') == title and 'pull_request' not in issue:
                return issue['html_url'], False
        if dry:
            print(json.dumps({'title': title, 'labels': labels, 'body': body}))
            return None, False
        if self.label_cache is None:
            self.label_cache = {r['name'] for r in self.api(f'repos/{CENTRAL}/labels?per_page=100')}
        existing = self.label_cache
        for label in labels:
            if label not in existing:
                self.gh(['label', 'create', label, '--repo', CENTRAL, '--color', 'D93F0B'])
                existing.add(label)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt') as stream:
            stream.write(body)
            stream.flush()
            args = ['issue', 'create', '--repo', CENTRAL, '--title', title, '--body-file', stream.name]
            for label in labels:
                args += ['--label', label]
            url = self.gh(args).strip()
        if not re.fullmatch(r'https://github.com/djbclark/upstream-releases/issues/\d+', url):
            raise ValueError('issue create returned no valid URL; next run will reconcile by title')
        issues.append({'title': title, 'html_url': url})
        return url, True

    def run(self, registry_path, state_path, dry=False, force=False, interval=3600):
        data = registry(registry_path)  # Validate before any state/lock writes.
        self.remaining = None
        self.calls = 0
        self.issue_cache = self.label_cache = None
        warning = [owner for owner, c in data['owners'].items() if not c['complete']]
        if warning:
            text = 'coverage incomplete (credential-visible): ' + ', '.join(warning)
            print('WARNING: ' + text)
            # Partial inventory must never change prior state or open alerts.
            if not dry:
                try:
                    self.ping('upstream-release: ' + text)
                except (OSError, subprocess.SubprocessError):
                    pass
            return
        print('coverage: complete (credential-visible only)')
        path = Path(state_path)
        if dry:
            return self.check(data, path, dry, force, interval)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self.check(data, path, dry, force, interval)

    def check(self, data, path, dry, force, interval):
        state = json.loads(path.read_text()) if path.exists() else {'upstreams': {}}
        now = self.clock()
        opened = []
        errors = []
        for row in data['components']:
            if not row['watch_releases']:
                continue
            repo = row['upstream_repo']
            previous = state['upstreams'].get(repo)
            if previous and not force and now - previous.get('checked_at', 0) < interval:
                continue
            try:
                events = self.snapshot(repo, now)
                if previous is None:
                    print(f'{repo}: baseline {len(events)} tags; no issues')
                    if not dry:
                        state['upstreams'][repo] = {'baseline_at': stamp(now), 'seen': sorted(events), 'issues': {}, 'checked_at': now}
                        save(path, state)
                    continue
                for tag in sorted(events.keys() - set(previous['seen'])):
                    url, created = self.issue(row, tag, events[tag], dry)
                    if dry:
                        continue
                    previous['issues'][tag] = url
                    previous['seen'].append(tag)
                    save(path, state)  # Commit each issue only after it exists.
                    if created:
                        opened.append(f'{repo} {tag} {url}')
                if not dry:
                    previous['checked_at'] = now
                    save(path, state)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                errors.append(f'{repo}: {type(error).__name__} (fetch/create failed; will retry)')
        if not dry:
            state['last_run'] = stamp(now)
            save(path, state)
        if opened:
            try:
                self.ping('upstream-release: ' + '; '.join(opened))
            except (OSError, subprocess.SubprocessError):
                print('WARNING: hermes-ping failed; issues remain recorded', file=sys.stderr)
        if errors:
            raise ValueError('; '.join(errors))



def paseo_status(registry_path, state_path):
    """Read-only terminal status; never launches the app or calls a model."""
    data = registry(registry_path)
    row = next((r for r in data['components'] if r['upstream_repo'].lower() == 'getpaseo/paseo'), None)
    if row is None:
        raise ValueError('registry has no paseo row')
    tags = Watcher().api(f'repos/{row["upstream_repo"]}/tags?per_page=100')
    versions = []
    for tag in tags:
        name = tag['name']
        match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)[.-]?(\d+)?)?(?:\+.*)?', name)
        if match:
            major, minor, patch, pre, number = match.groups()
            key = (int(major), int(minor), int(patch), {None: 3, 'rc': 2, 'beta': 1, 'alpha': 0}[pre], int(number or 0))
            versions.append((key, name))
    newest = max(versions)[1] if versions else 'unknown'
    base = command(['git', '-C', str(Path.home()/'src/paseo-beta2-local-wt'),
                    'describe', '--tags', '--abbrev=0', '--match', 'v*']).strip()
    installed = Watcher.app_version(row)
    issues = json.loads(command(['gh', 'issue', 'list', '--repo', CENTRAL, '--label', 'radar',
                                 '--state', 'open', '--limit', '1000', '--json', 'number,title,url']))
    titles = [i['title'] for i in issues if i['title'].startswith('[radar][urgent] Upstream getpaseo/paseo release ')]
    state = json.loads(Path(state_path).read_text()) if Path(state_path).exists() else {}
    print(json.dumps({'upstream_tag': newest, 'fork_base_tag': base, 'installed_version': installed,
                      'installed_matches_base': installed == base.lstrip('v'),
                      'last_watcher_run': state.get('last_run', 'never'),
                      'open_alert_count': len(titles), 'open_alert_titles': titles}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default=str(Path.home()/'.local/state/djbclark-ade/forks/registry.json'))
    parser.add_argument('--state', default=str(Path.home()/'.local/state/fleet-watch/upstream-release.json'))
    parser.add_argument('--status', action='store_true', help='read-only Paseo terminal status')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--once', action='store_true', help='force an immediate single check, bypassing cache interval')
    parser.add_argument('--interval', type=int, default=3600)
    args = parser.parse_args()
    try:
        if args.status:
            paseo_status(args.registry, args.state)
        else:
            Watcher().run(args.registry, args.state, args.dry_run, args.once, args.interval)
        return 0
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        print(f'upstream-release: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
