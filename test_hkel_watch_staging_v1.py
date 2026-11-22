#!/usr/bin/env python3
"""Synthetic Cap123/HTTP regression. No external network, DB or real state."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import urllib.error
import zipfile

import hkel_watch_staging_v1 as mod


def fixture(date='2026-03-01', text='Synthetic source fixture; do not use as actual legal advice.'):
    stamp = date.replace('-', '') + '000000'
    selected = {'VersionDate': {'value': date+'T00:00:00', 'isCurrentVersion': True,
                'isPencilMarked': False, 'statusCategory': 'InEffect', 'statusCode': '1'},
                'DataResourceUrl': mod.ARCHIVE_URL, 'FileLocation': 'cap_123_en_c',
                'FileName': 'cap_123_'+stamp+'_en_c.xml', 'Web': mod.WEB_URL}
    manifest = {'UpdatedDateTime': '2026-11-16T21:27:40', 'Chapter': [
        {'CapNo': '123', 'ChapterTitleEnglish': 'Buildings Ordinance',
         'LegislationType': 'O', 'PrincipalOrdinance': '123', 'Version': [selected]}]}
    xml = (f'<ordinance xmlns="{mod.NS}" xmlns:dc="{mod.DC}" xml:lang="en"><meta>'
           f'<docNumber>123</docNumber><docStatus>In effect</docStatus>'
           f'<dc:identifier>/hk/cap123!en</dc:identifier><dc:date>{date}</dc:date>'
           '<dc:language>en</dc:language><dc:publisher>DoJ</dc:publisher>'
           '<dc:rights>the Government of the Hong Kong Special Administrative Region</dc:rights>'
           '</meta><main><section name="s1" id="s1"><num>1.</num>'
           f'<heading>Fixture</heading><content>{text}</content></section></main></ordinance>').encode()
    return json.dumps(manifest).encode(), xml


def invoke(root, data=None, **kwargs):
    manifest, xml = data or fixture()
    return mod.run(state_root=root, manifest_raw=manifest, xml=xml, **kwargs)


def snapshot(root):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


class Response:
    def __init__(self, url, status, body=b'', headers=None):
        self.url, self.status, self.body = url, status, io.BytesIO(body)
        self.headers = headers or {}
        self.reads = 0
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, size=-1):
        self.reads += 1
        return self.body.read(size)
    read1 = read


class FakeOfficial:
    def __init__(self, data=None, *, ignore_range=False, range_mismatch=False, etag='"fixture"', duplicate=False, changed_etag=False):
        self.manifest, self.xml = data or fixture()
        info = json.loads(self.manifest)['Chapter'][0]['Version'][0]
        member = info['FileLocation']+'/'+info['FileName']
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member, self.xml)
            if duplicate:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    archive.writestr(member, self.xml)
        self.archive = stream.getvalue()
        self.ignore_range, self.range_mismatch, self.etag = ignore_range, range_mismatch, etag
        self.changed_etag = changed_etag
        self.calls, self.range_responses = [], []
    def open(self, request, timeout):
        url = request.full_url
        self.calls.append((url, request.get_method()))
        assert 0 < timeout <= 15
        if url == mod.MASTER_URL:
            return Response(url, 200, self.manifest, {'Content-Length': str(len(self.manifest))})
        assert url == mod.ARCHIVE_URL
        if request.get_method() == 'HEAD':
            return Response(url, 200, headers={'content-length': str(len(self.archive)), 'etag': self.etag})
        assert request.get_header('If-match') == self.etag
        start, end = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
        body = self.archive[start:end+1]
        headers = {'Content-Range': f'bytes {start}-{end}/{len(self.archive)}',
                   'Content-Length': str(len(body)), 'ETag': '"changed"' if self.changed_etag else self.etag}
        if self.range_mismatch:
            headers['Content-Range'] = 'bytes 0-0/1'
        response = Response(url, 200 if self.ignore_range else 206, body, headers)
        self.range_responses.append(response)
        return response


@contextlib.contextmanager
def official(server):
    with patch.object(mod.urllib.request, 'build_opener', return_value=server), \
         patch('socket.socket.connect', side_effect=AssertionError('real network forbidden')), \
         patch('subprocess.Popen', side_effect=AssertionError('subprocess forbidden')):
        yield server


def test_default_is_no_network_no_workspace_and_never_no_change_without_baseline():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)/'hkel-watch-staging'
        with patch.object(mod, 'fetch_official', side_effect=AssertionError('unexpected network')):
            empty = mod.run(state_root=root)
            inspected = invoke(root)
        assert empty['status'] == inspected['status'] == 'BASELINE_REQUIRED', inspected
        assert not root.exists() and inspected['parse_stats']['records'] == 1
        assert inspected['input_provenance'] == 'operator-supplied'
        for key in ('state_written', 'production_access', 'production_write', 'drive_write',
                    'db_access', 'model_api_used', 'scheduled_watch', 'legal_currentness_verified', 'semantic_verified'):
            assert inspected[key] is False, key


def test_official_fetch_uses_bounded_ranges_and_creates_no_state():
    with tempfile.TemporaryDirectory() as temp, official(FakeOfficial()) as server:
        root = Path(temp)/'hkel-watch-staging'
        result = mod.run(state_root=root, fetch=True)
        assert result['status'] == 'BASELINE_REQUIRED', result
        assert result['observed']['xml_sha256'] == mod.digest(server.xml)
        assert result['transport']['range_bytes'] <= mod.MAX_RANGE_TOTAL
        assert result['transport']['range_requests'] > 0 and not root.exists()
        assert result['input_provenance'] == 'official-https'


def test_ignored_range_mismatched_range_and_weak_etag_fail_before_body():
    for options in ({'ignore_range': True}, {'range_mismatch': True}, {'etag': 'W/"weak"'}, {'changed_etag': True}):
        with tempfile.TemporaryDirectory() as temp, official(FakeOfficial(**options)) as server:
            result = mod.run(state_root=Path(temp)/'hkel-watch-staging', fetch=True)
            assert result['status'] == 'BLOCKED', result
            assert all(r.reads == 0 for r in server.range_responses)


def test_duplicate_zip_member_and_oversized_xml_fail_closed():
    with tempfile.TemporaryDirectory() as temp, official(FakeOfficial(duplicate=True)):
        result = mod.run(state_root=Path(temp)/'hkel-watch-staging', fetch=True)
        assert result['status'] == 'BLOCKED' and 'xml_member_missing_or_ambiguous' in result['reasons'], result
    with tempfile.TemporaryDirectory() as temp:
        manifest, _ = fixture()
        result = invoke(Path(temp)/'hkel-watch-staging', (manifest, b'x'*(mod.MAX_XML+1)))
        assert result['status'] == 'BLOCKED', result


def test_missing_ambiguous_and_wrong_source_identity_fail_without_state():
    base, xml = fixture()
    for change in ('missing', 'duplicate-chapter', 'duplicate-version', 'wrong-title', 'wrong-host', 'pencil', 'unknown-status'):
        data = json.loads(base)
        chapter = data['Chapter'][0]
        version = chapter['Version'][0]
        if change == 'missing':
            data['Chapter'] = []
        elif change == 'duplicate-chapter':
            data['Chapter'].append(copy.deepcopy(chapter))
        elif change == 'duplicate-version':
            chapter['Version'].append(copy.deepcopy(version))
        elif change == 'wrong-title':
            chapter['ChapterTitleEnglish'] = 'Other Ordinance'
        elif change == 'wrong-host':
            version['DataResourceUrl'] = 'http://127.0.0.1/private.zip'
        elif change == 'pencil':
            version['VersionDate']['isPencilMarked'] = True
        else:
            version['VersionDate']['statusCode'] = 'UNKNOWN'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'hkel-watch-staging'
            result = invoke(root, (json.dumps(data).encode(), xml))
            assert result['status'] == 'BLOCKED' and not root.exists(), (change, result)


def test_xml_identity_date_language_dtd_and_parse_errors_are_rejected():
    manifest, xml = fixture()
    bad = [xml.replace(b'<docNumber>123', b'<docNumber>572'),
           xml.replace(b'2026-03-01', b'2026-04-01'), xml.replace(b'xml:lang="en"', b'xml:lang="zh"'),
           xml.replace(mod.DC.encode(), b'https://untrusted.example/meta'),
           xml.decode().encode('utf-16'), b'<!DOCTYPE ordinance>'+xml, b'<not-well-formed']
    for raw in bad:
        with tempfile.TemporaryDirectory() as temp:
            result = invoke(Path(temp)/'hkel-watch-staging', (manifest, raw))
            assert result['status'] == 'BLOCKED', result


def test_unapproved_urls_redirects_deadline_and_budgets_refuse_before_connection():
    with official(FakeOfficial()) as server:
        reader = mod.PublicReader()
        calls = [lambda: reader.request('http://127.0.0.1/private'),
                 lambda: reader.request(mod.ARCHIVE_URL, start=0, size=mod.MAX_RANGE+1,
                                        total=mod.MAX_RANGE*2, etag='"x"'),
                 lambda: mod.NoRedirect().redirect_request(None, None, None, None, None, None)]
        for call in calls:
            try:
                call()
            except mod.WatchRefused:
                pass
            else:
                raise AssertionError('unsafe transport accepted')
        with patch.object(mod.time, 'monotonic', return_value=reader.deadline+1):
            try:
                reader.request(mod.MASTER_URL)
            except mod.WatchRefused:
                pass
            else:
                raise AssertionError('deadline ignored')
        assert not server.calls


def test_provider_and_invalid_metadata_diagnostics_do_not_leak():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)/'hkel-watch-staging'
        with patch.object(mod.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = urllib.error.URLError('PRIVATE PROVIDER DETAIL')
            result = mod.run(state_root=root, fetch=True)
        assert result['status'] == 'BLOCKED' and 'PRIVATE PROVIDER' not in json.dumps(result)
        raw, xml = fixture()
        manifest = json.loads(raw)
        manifest['Chapter'][0]['Version'][0]['VersionDate']['value'] = 'PRIVATE INPUT DETAIL'
        result = invoke(root, (json.dumps(manifest).encode(), xml))
        assert result['status'] == 'BLOCKED' and 'PRIVATE INPUT' not in json.dumps(result)


def test_production_and_traversal_roots_are_refused():
    for root in (Path('/opt/ai-knowledge/watch/hkel-watch-staging'), Path('/tmp/production/hkel-watch-staging'),
                 Path('/tmp/a/../hkel-watch-staging'), Path('hkel-watch-staging')):
        result = invoke(root)
        assert result['status'] == 'BLOCKED', result


def test_cli_write_flags_and_fixed_roots_are_required():
    with contextlib.redirect_stderr(io.StringIO()):
        for args in (['--initialize-baseline'], ['--save-candidate'], ['--confirm-staging-write'],
                     ['--initialize-baseline', '--confirm-staging-write'], ['--state-root', '/tmp/test'],
                     ['--manifest', '/tmp/data'], ['--fetch-official', '--manifest', '/tmp/data', '--xml', '/tmp/data']):
            try:
                mod.main(args)
            except SystemExit as exc:
                assert exc.code == 2
            else:
                raise AssertionError('unsafe CLI accepted')
    with patch.object(mod, 'check_checkout'), patch.object(mod, 'scope'), patch.object(mod, 'run') as run, \
         contextlib.redirect_stdout(io.StringIO()):
        for status, code in [('BLOCKED', 2), ('BASELINE_REQUIRED', 3), ('CHANGED_REVIEW_REQUIRED', 3),
                             ('NO_CHANGE', 0), ('READY_FOR_OFFICIAL_CHECK', 0)]:
            run.return_value = {'status': status}
            assert mod.main([]) == code


def test_storage_initialize_idempotence_and_no_change_are_immutable():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)/'hkel-watch-staging'
        first = invoke(root, action='initialize-baseline')
        assert first['status'] == 'BASELINE_INITIALIZED', first
        saved = snapshot(root)
        repeat = invoke(root, action='initialize-baseline')
        normal = invoke(root)
        assert repeat['status'] == 'BASELINE_ALREADY_INITIALIZED' and normal['status'] == 'NO_CHANGE', (repeat, normal)
        assert saved == snapshot(root) and normal['state_written'] is False
        assert normal['baseline_record_sha256_before'] == normal['baseline_record_sha256_after']
        ready = mod.run(state_root=root)
        assert ready['status'] == 'READY_FOR_OFFICIAL_CHECK'


def test_storage_changed_and_same_date_changed_bytes_do_not_advance_baseline():
    for data in (fixture(date='2026-04-01'), fixture(text='Changed bytes on the same publisher date.')):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'hkel-watch-staging'
            assert invoke(root, action='initialize-baseline')['status'] == 'BASELINE_INITIALIZED'
            before = (root/'baseline.json').read_bytes()
            planned = invoke(root, data)
            assert planned['status'] == 'CHANGED_REVIEW_REQUIRED' and not planned['state_written'], planned
            staged = invoke(root, data, action='save-candidate')
            assert staged['status'] == 'CHANGED_REVIEW_REQUIRED' and staged['state_written'], staged
            assert (root/'baseline.json').read_bytes() == before
            saved = snapshot(root)
            repeated = invoke(root, data, action='save-candidate')
            assert repeated['status'] == 'CHANGED_REVIEW_REQUIRED' and snapshot(root) == saved, repeated
            refused = invoke(root, data, action='initialize-baseline')
            assert refused['status'] == 'BLOCKED' and (root/'baseline.json').read_bytes() == before


def test_storage_candidate_requires_baseline_and_stale_lock_blocks():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)/'hkel-watch-staging'
        missing = invoke(root, action='save-candidate')
        assert missing['status'] == 'BASELINE_REQUIRED' and not root.exists(), missing
        root.mkdir()
        (root/'.lock').mkdir()
        result = invoke(root, action='initialize-baseline')
        assert result['status'] == 'BLOCKED' and (root/'.lock').is_dir(), result


def test_storage_xml_tamper_and_baseline_record_tamper_block():
    for target in ('source.xml', 'edition.json'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'hkel-watch-staging'
            result = invoke(root, action='initialize-baseline')
            folder = root/'editions'/mod.CAP/result['edition_id']
            (folder/target).write_bytes(b'tampered')
            blocked = invoke(root)
            assert blocked['status'] == 'BLOCKED', blocked


def test_storage_registry_drift_and_baseline_drift_during_fetch_block():
    for target in ('registry', 'baseline'):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'hkel-watch-staging'
            assert invoke(root, action='initialize-baseline')['status'] == 'BASELINE_INITIALIZED'
            original = mod.REGISTRY.read_bytes()
            real_read = Path.read_bytes
            changed = [False]
            def read(path):
                if path == mod.REGISTRY and target == 'registry' and changed[0]:
                    return original+b'\n# synthetic drift\n'
                return real_read(path)
            def fetch(registry):
                changed[0] = True
                if target == 'baseline':
                    (root/'baseline.json').write_bytes(b'{}')
                return (*fixture(), {})
            with patch.object(Path, 'read_bytes', read), patch.object(mod, 'fetch_official', side_effect=fetch):
                blocked = mod.run(state_root=root, fetch=True)
            assert blocked['status'] == 'BLOCKED', blocked


def test_storage_symlink_state_and_artifacts_refuse():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        target = base/'other'
        target.mkdir()
        root = base/'hkel-watch-staging'
        root.symlink_to(target, target_is_directory=True)
        assert invoke(root)['status'] == 'BLOCKED'
        root.unlink()
        created = invoke(root, action='initialize-baseline')
        folder = root/'editions'/mod.CAP/created['edition_id']
        raw = (folder/'source.xml').read_bytes()
        outside = base/'outside.xml'
        outside.write_bytes(raw)
        (folder/'source.xml').unlink()
        (folder/'source.xml').symlink_to(outside)
        assert invoke(root)['status'] == 'BLOCKED'


def test_storage_world_writable_state_and_partial_writes_are_reported():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)/'hkel-watch-staging'
        root.mkdir()
        root.chmod(0o777)
        try:
            assert invoke(root)['status'] == 'BLOCKED'
        finally:
            root.chmod(0o700)
        with patch.object(mod, 'atomic_bundle', side_effect=OSError('synthetic write failure')):
            result = invoke(root, action='initialize-baseline')
        assert result['status'] == 'BLOCKED' and result['state_write_attempted'], result
        assert result['partial_state_may_exist'] is True
        assert not (root/'.lock').exists()


def main():
    cases = sorted((name, fn) for name, fn in globals().items() if name.startswith('test_') and callable(fn))
    with patch('socket.socket.connect', side_effect=AssertionError('external network forbidden')), \
         patch('subprocess.Popen', side_effect=AssertionError('subprocess forbidden')):
        for name, fn in cases:
            fn()
            print(name+': PASS')
    print('HKEL CAP123 STAGING MANUAL WATCH: PASS')


if __name__ == '__main__':
    main()
