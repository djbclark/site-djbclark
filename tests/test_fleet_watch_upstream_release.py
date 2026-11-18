"""Offline release radar checks. No GitHub writes, network or real notification."""
import importlib.util
import json
from pathlib import Path
import subprocess
import pytest

SPEC = importlib.util.spec_from_file_location('radar', Path(__file__).resolve().parents[1]/'bin/fleet_watch_upstream_release.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class Fake:
    def __init__(self):
        self.tags = ['v1']; self.releases = []; self.issues = []; self.created = []; self.labels = []
        self.fail_create = False; self.fail_tags = False
    def __call__(self, args):
        if args[0] == 'api':
            path = args[1]
            if path == 'rate_limit':
                return json.dumps({'resources': {'core': {'remaining': 5000}}})
            if '/tags?' in path:
                if self.fail_tags:
                    raise ValueError('fetch failed')
                rows = [{'name': t} for t in self.tags]
            elif '/releases?' in path:
                rows = self.releases
            elif '/issues?' in path:
                rows = self.issues
            elif '/git/ref/tags/' in path:
                return json.dumps({'object': {'type': 'commit', 'sha': 'abc'}})
            elif '/git/tags/' in path:
                return json.dumps({'tagger': {'date': '2026-11-18T09:00:00Z'}})
            elif '/commits/' in path:
                return json.dumps({'commit': {'committer': {'date': '2026-11-18T10:00:00Z'}}})
            else:
                rows = [{'name': label} for label in self.labels]
            return json.dumps(rows)
        if args[:2] == ['label', 'create']:
            self.labels.append(args[2]); return ''
        if self.fail_create:
            raise ValueError('create failed')
        title = args[args.index('--title')+1]
        body = Path(args[args.index('--body-file')+1]).read_text()
        labels = [args[i+1] for i, arg in enumerate(args) if arg == '--label']
        url = f'https://github.com/djbclark/upstream-releases/issues/{len(self.issues)+1}'
        self.issues.append({'title': title, 'html_url': url, 'state': 'closed'})
        self.created.append((title, body, labels))
        return url


@pytest.fixture
def setup(tmp_path):
    reg = tmp_path/'registry.json'; state = tmp_path/'state.json'
    data = {'schema_version': 1, 'generated_at': '2026-11-18T00:00:00Z',
            'owners': {o: {'complete': True, 'scope': 'credential-visible', 'error': None} for o in ('djbclark', 'djbcsipb', 'frdminc')},
            'components': [{'upstream_repo': 'getpaseo/paseo', 'fork_repo': 'djbclark/paseo',
                            'base_tag': None, 'watch_releases': True}]}
    for row in data['components']:
        row.update(id='paseo', private=False, catalog_ids=['paseo'], upstream='https://github.com/'+row['upstream_repo'], fork='https://github.com/'+row['fork_repo'])
    reg.write_text(json.dumps(data)); fake = Fake(); pings = []
    watcher = m.Watcher(fake, lambda: 1800000000, pings.append, lambda row: 'n/a')
    def run(dry=False):
        watcher.run(reg, state, dry=dry, force=True)
    return reg, state, data, fake, watcher, pings, run


def test_baseline_and_new_tag_exact_contract(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); assert not fake.created and not pings
    assert json.loads(state.read_text())['upstreams']['getpaseo/paseo']['baseline_at']
    fake.tags.append('v2'); run(); run()
    assert len(fake.created) == 1 and len(pings) == 1
    title, body, labels = fake.created[0]
    assert title == '[radar][urgent] Upstream getpaseo/paseo release v2'
    assert labels == ['radar', 'urgent', 'upstream-release', 'fork:paseo']
    assert body == '\n'.join(['Upstream: getpaseo/paseo', 'Fork: djbclark/paseo', 'Tag: v2',
        'Release URL: https://github.com/getpaseo/paseo/releases/tag/v2',
        'Published (UTC): 2026-11-18T10:00:00Z', 'Kind: stable', 'Our fork base tag: unknown',
        'Installed app version: n/a', 'Action: review changelog; check whether our open upstream issues are fixed; fork needs rebase'])
    assert str(reg.parent) not in body and 'token' not in body


def test_crash_recovery_closed_title_prevents_duplicate(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); before = state.read_bytes(); fake.tags.append('v2'); run()
    state.write_bytes(before); run()
    assert len(fake.created) == 1


def test_several_tags_beta_and_prerelease(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); fake.tags += ['v2-beta.2', 'v2-rc.1', 'v2-alpha', 'v3']
    fake.releases = [{'tag_name': 'v3', 'prerelease': True, 'published_at': '2026-11-18T00:00:00Z'}]
    run(); assert len(fake.created) == 4 and len(pings) == 1
    assert all('Kind: beta' in body for _, body, _ in fake.created)


def test_partial_preserves_state_and_warns(setup, capsys):
    reg, state, data, fake, watcher, pings, run = setup
    run(); before = state.read_bytes(); fake.tags.append('v2')
    data['owners']['djbclark']['complete'] = False; reg.write_text(json.dumps(data)); run()
    assert state.read_bytes() == before and not fake.created
    assert 'coverage incomplete' in capsys.readouterr().out and 'coverage incomplete' in pings[-1]


@pytest.mark.parametrize('value', ['{', '{}', '{"schema_version":2}', '{"schema_version":true}'])
def test_bad_registry_unchanged(setup, value):
    reg, state, data, fake, watcher, pings, run = setup
    run(); before = state.read_bytes(); reg.write_text(value)
    with pytest.raises(ValueError, match='registry'):
        run()
    assert state.read_bytes() == before and not fake.created


def test_missing_registry_no_state(setup):
    reg, state, data, fake, watcher, pings, run = setup
    reg.unlink()
    with pytest.raises(ValueError): run()
    assert not state.exists()


def test_ping_failure_ignored_and_create_failure_retried(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); fake.tags.append('v2'); fake.fail_create = True
    with pytest.raises(ValueError): run()
    assert 'v2' not in json.loads(state.read_text())['upstreams']['getpaseo/paseo']['seen']
    fake.fail_create = False
    def fail(text): raise subprocess.TimeoutExpired('ping', 1)
    watcher.ping = fail; run(); run(); assert len(fake.created) == 1


def test_dry_run_no_mutation_and_failed_fetch_no_baseline(setup, capsys):
    reg, state, data, fake, watcher, pings, run = setup
    fake.fail_tags = True
    with pytest.raises(ValueError): run()
    assert not json.loads(state.read_text())['upstreams']
    fake.fail_tags = False; run(); before = state.read_bytes(); fake.tags.append('v2')
    run(True)
    assert state.read_bytes() == before and not fake.created and not fake.labels
    assert '[radar][urgent]' in capsys.readouterr().out


def test_new_registry_repo_baselined_and_cache(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); fake.tags.append('v2'); watcher.run(reg, state)
    assert not fake.created
    data['components'].append({'upstream_repo': 'other/project', 'fork_repo': 'djbclark/project', 'base_tag': None, 'watch_releases': True, 'id': 'project', 'private': False, 'catalog_ids': [], 'upstream': 'https://github.com/other/project', 'fork': 'https://github.com/djbclark/project'})
    reg.write_text(json.dumps(data)); watcher.run(reg, state)
    assert not fake.created and 'other/project' in json.loads(state.read_text())['upstreams']


def test_missing_owner_or_component_fields_hold(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); before = state.read_bytes()
    del data['owners']['frdminc']; reg.write_text(json.dumps(data))
    with pytest.raises(ValueError): run()
    assert state.read_bytes() == before


def test_rate_reserve_holds_before_fetch(setup):
    reg, state, data, fake, watcher, pings, run = setup
    original = fake.__call__
    def limited(args):
        if args == ['api', 'rate_limit']:
            return json.dumps({'resources': {'core': {'remaining': 499}}})
        return original(args)
    watcher.transport = limited
    with pytest.raises(ValueError): run()
    assert not json.loads(state.read_text())['upstreams'] and not fake.created


def test_annotated_tag_uses_tagger_date(setup):
    reg, state, data, fake, watcher, pings, run = setup
    run(); fake.tags.append('v2')
    original = fake.__call__
    def annotated(args):
        if args[0] == 'api' and '/git/ref/tags/' in args[1]:
            return json.dumps({'object': {'type': 'tag', 'sha': 'abc'}})
        return original(args)
    watcher.transport = annotated; run()
    assert 'Published (UTC): 2026-11-18T09:00:00Z' in fake.created[0][1]


def test_paseo_status_semver_and_titles_only(setup, monkeypatch, capsys):
    reg, state, data, fake, watcher, pings, run = setup
    monkeypatch.setattr(m.Watcher, 'api', lambda self, path: [{'name': 'v0.16.0'}, {'name': 'v0.17.0-beta.2'}, {'name': 'v0.17.0-beta.10'}])
    monkeypatch.setattr(m.Watcher, 'app_version', staticmethod(lambda row: '0.16.0'))
    def cmd(argv):
        if argv[0] == 'git':
            assert argv[1] == '-C'
            return 'v0.16.0'
        assert argv[:3] == ['gh', 'issue', 'list']
        return json.dumps([{'title': '[radar][urgent] Upstream getpaseo/paseo release v2', 'body': 'UNTRUSTED BODY'}, {'title': 'other'}])
    monkeypatch.setattr(m, 'command', cmd)
    m.paseo_status(reg, state)
    result = json.loads(capsys.readouterr().out)
    assert result['upstream_tag'] == 'v0.17.0-beta.10'
    assert result['installed_matches_base'] is True
    assert result['open_alert_count'] == 1
    assert 'UNTRUSTED BODY' not in str(result)
