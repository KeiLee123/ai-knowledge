#!/usr/bin/env python3
"""Cap.123 manual Staging watch. Default: no network and no filesystem writes.

Explicit --fetch-official reads bounded public HTTPS data into memory. Separate
confirmed modes can initialize an immutable baseline or save a changed edition.
No Production paths, Drive, DB, model, timer, source promotion or legal approval.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib

import yaml
import law_watch as legacy
from m10b1_isolated_candidate_v1 import atomic_bundle, safe_mkdir, write_candidate_copy
import parse_hkel_xml_v5 as parser_v5

VERSION = 'hkel-cap123-manual-staging-watch-v1'
STATE_ROOT = Path('/var/lib/jason-os/hkel-watch-staging')
REGISTRY = Path(__file__).resolve().with_name('legislation_registry.yaml')
CAP = 'CAP_123'
MASTER_URL = legacy.MASTER_URL
ARCHIVE_URL = 'https://resource.data.one.gov.hk/doj/data/hkel_c_leg_cap_1_cap_300_en.zip'
WEB_URL = 'https://www.elegislation.gov.hk/hk/cap123!en'
TERMS_URL = 'https://data.gov.hk/en/terms-and-conditions'
ATTRIBUTION = 'HKSAR Government / Department of Justice / DATA.GOV.HK'
NS = 'http://www.xml.gov.hk/schemas/hklm/1.0'
DC = 'http://purl.org/dc/elements/1.1/'
MAX_MANIFEST = 10 * 1024 * 1024
MAX_XML = 2 * 1024 * 1024
MAX_RANGE = 4 * 1024 * 1024
MAX_RANGE_TOTAL = 8 * 1024 * 1024
SHA = re.compile(r'[a-f0-9]{64}\Z')


class WatchRefused(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise WatchRefused(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def scope(root):
    root = Path(root)
    need(root.is_absolute() and root.name == STATE_ROOT.name and '..' not in root.parts,
         'staging_state_root_required')
    need(not any(p.lower() in {'ai-knowledge', 'production'} for p in root.parts),
         'production_path_forbidden')
    for p in (root, *root.parents):
        need(not p.is_symlink(), 'state_parent_symlink')
    if root.exists():
        need(root.is_dir(), 'state_root_not_directory')
        if os.name == 'posix':
            need(not root.stat().st_mode & 0o022, 'state_root_writable_by_others')
    return root


def read_file(path, root, limit):
    path, root = Path(path), Path(root)
    need(path.is_absolute() and path.is_relative_to(root) and '..' not in path.parts,
         'artifact_outside_staging')
    node = path
    while node != root:
        need(not node.is_symlink(), 'artifact_symlink')
        node = node.parent
    need(not root.is_symlink() and path.is_file() and path.stat().st_size <= limit,
         'artifact_missing_or_oversized')
    raw = path.read_bytes()
    need(len(raw) <= limit, 'artifact_grew_during_read')
    return raw


def identity(manifest, registry):
    need(isinstance(registry, dict) and isinstance(registry.get('defaults'), dict)
         and isinstance(registry.get('legislation'), dict), 'registry_schema_invalid')
    source = registry['legislation'].get(CAP)
    need(isinstance(source, dict), 'registry_chapter_missing')
    need(registry['defaults']['source_of_truth'] == 'HKeL'
         and source.get('enabled') is True and str(source['chapter']) == '123'
         and source['title'] == 'Buildings Ordinance', 'registry_identity_mismatch')
    need(isinstance(manifest, dict) and isinstance(manifest.get('Chapter'), list), 'invalid_manifest_chapters')
    need(all(isinstance(c, dict) for c in manifest['Chapter']), 'invalid_chapter_record')
    chapters = [c for c in manifest['Chapter'] if str(c.get('CapNo', '')).strip() == '123']
    need(len(chapters) == 1, 'chapter_missing_or_ambiguous')
    chapter = legacy.build_chapter_index(manifest)['123']
    need(chapter['ChapterTitleEnglish'] == source['title']
         and chapter['LegislationType'] == 'O'
         and str(chapter['PrincipalOrdinance']) == '123', 'manifest_identity_mismatch')
    versions = chapter.get('Version', [])
    versions = [versions] if isinstance(versions, dict) else versions
    need(isinstance(versions, list), 'invalid_version_list')
    need(all(isinstance(v, dict) and isinstance(v.get('VersionDate'), dict) for v in versions),
         'invalid_version_record')
    current = [v for v in versions if v.get('VersionDate', {}).get('isCurrentVersion') is True]
    need(len(current) == 1, 'current_version_missing_or_ambiguous')
    version = legacy.get_current_version(chapter)
    vd = version['VersionDate']
    need(vd.get('statusCategory') == 'InEffect' and vd.get('statusCode') == '1'
         and vd.get('isPencilMarked') is False, 'version_status_requires_review')
    date = datetime.fromisoformat(vd['value'])
    filename = 'cap_123_' + date.strftime('%Y%m%d%H%M%S') + '_en_c.xml'
    need(version['DataResourceUrl'] == ARCHIVE_URL and version['Web'] == WEB_URL
         and version['FileLocation'] == 'cap_123_en_c' and version['FileName'] == filename,
         'resource_identity_mismatch')
    return {'chapter': CAP, 'title': source['title'], 'version_date': vd['value'],
            'status_category': vd['statusCategory'], 'status_code': vd['statusCode'],
            'pencil_marked': False, 'archive_url': ARCHIVE_URL, 'web_url': WEB_URL,
            'member': 'cap_123_en_c/' + filename}


def inspect_xml(raw, selected):
    need(isinstance(raw, bytes) and 0 < len(raw) <= MAX_XML, 'xml_size_invalid')
    text = raw.decode('utf-8-sig')
    need('\x00' not in text and '<!DOCTYPE' not in text.upper()
         and '<!ENTITY' not in text.upper(), 'xml_dtd_or_encoding_forbidden')
    root = ET.fromstring(text)
    need(root.tag == '{' + NS + '}ordinance'
         and root.get('{http://www.w3.org/XML/1998/namespace}lang') == 'en', 'xml_root_identity_mismatch')
    metas = root.findall('{' + NS + '}meta')
    need(len(metas) == 1, 'xml_meta_missing_or_ambiguous')
    def field(name):
        namespace = NS if name in {'docNumber', 'docStatus'} else DC
        nodes = metas[0].findall('{' + namespace + '}' + name)
        need(len(nodes) == 1, 'xml_meta_field_missing_or_ambiguous')
        return parser_v5.clean_text(nodes[0])
    expected = {'docNumber': '123', 'docStatus': 'In effect', 'identifier': '/hk/cap123!en', 'language': 'en',
                'publisher': 'DoJ', 'date': selected['version_date'][:10],
                'rights': 'the Government of the Hong Kong Special Administrative Region'}
    need(all(field(k) == v for k, v in expected.items()), 'xml_version_or_publisher_mismatch')
    # Check raw references before legacy deduplication can hide conflicting text.
    records = parser_v5.walk(root)
    refs = [r['canonical_reference'] for r in records if r.get('canonical_reference')]
    need(records and refs and max(Counter(refs).values()) == 1, 'empty_or_duplicate_canonical_refs')
    records = parser_v5.deduplicate(records)
    return {'records': len(records), 'exact_ref_eligible': sum(bool(r['exact_ref_eligible']) for r in records),
            'duplicate_canonical_refs': 0}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise WatchRefused('official_redirect_refused')


class PublicReader:
    """Fixed public URLs, bounded reads and a deadline checked between reads."""
    def __init__(self):
        self.deadline = time.monotonic() + 60
        self.opener = urllib.request.build_opener(NoRedirect())
        self.range_bytes = 0
        self.range_requests = 0

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        need(seconds > 0, 'official_read_deadline_exceeded')
        return min(15, seconds)

    def request(self, url, *, head=False, start=None, size=None, total=None, etag=None):
        need(url in {MASTER_URL, ARCHIVE_URL}, 'unapproved_official_url')
        headers = {'User-Agent': 'Jason-OS-HKeL-Staging-Watch/1.0', 'Accept-Encoding': 'identity'}
        if start is not None:
            need(url == ARCHIVE_URL and 0 < size <= MAX_RANGE and start >= 0
                 and start + size <= total and self.range_requests < 20
                 and self.range_bytes + size <= MAX_RANGE_TOTAL, 'range_budget_exceeded')
            headers.update(Range=f'bytes={start}-{start+size-1}', **{'If-Match': etag})
            self.range_requests += 1
        req = urllib.request.Request(url, headers=headers, method='HEAD' if head else 'GET')
        try:
            with self.opener.open(req, timeout=self.remaining()) as response:
                need(response.geturl() == url, 'official_redirect_refused')
                if head:
                    need(response.status == 200, 'archive_head_failed')
                    return {k.lower(): v for k, v in response.headers.items()}
                limit = size if start is not None else MAX_MANIFEST
                need(response.status == (206 if start is not None else 200), 'range_or_manifest_status_refused')
                if start is not None:
                    need(response.headers.get('Content-Range') == f'bytes {start}-{start+size-1}/{total}',
                         'range_identity_mismatch')
                    need(response.headers.get('ETag') == etag, 'archive_etag_changed')
                declared = response.headers.get('Content-Length')
                need(declared is None or int(declared) <= limit, 'official_response_oversized')
                chunks, count = [], 0
                reader = getattr(response, 'read1', response.read)
                while True:
                    self.remaining()
                    part = reader(min(65536, limit + 1 - count))
                    if not part:
                        break
                    count += len(part)
                    need(count <= limit, 'official_response_oversized')
                    chunks.append(part)
                raw = b''.join(chunks)
                if start is not None:
                    need(len(raw) == size, 'truncated_archive_range')
                    self.range_bytes += len(raw)
                return raw
        except (urllib.error.URLError, OSError):
            raise WatchRefused('official_source_unavailable') from None


class RangedZip(io.RawIOBase):
    def __init__(self, reader):
        self.reader = reader
        headers = reader.request(ARCHIVE_URL, head=True)
        self.total = int(headers['content-length'])
        self.etag = headers['etag']
        need(0 < self.total <= 512*1024*1024 and re.fullmatch(r'"[^"\r\n]+"', self.etag),
             'invalid_archive_size_or_strong_etag')
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        need(whence in {0, 1, 2}, 'invalid_seek')
        pos = offset if whence == 0 else self.position + offset if whence == 1 else self.total + offset
        need(0 <= pos <= self.total, 'archive_seek_out_of_bounds')
        self.position = pos
        return pos

    def read(self, size=-1):
        size = self.total-self.position if size < 0 else min(size, self.total-self.position)
        if not size:
            return b''
        raw = self.reader.request(ARCHIVE_URL, start=self.position, size=size,
                                  total=self.total, etag=self.etag)
        self.position += len(raw)
        return raw


def fetch_official(registry):
    reader = PublicReader()
    manifest_raw = reader.request(MASTER_URL)
    selected = identity(json.loads(manifest_raw.decode('utf-8-sig')), registry)
    with RangedZip(reader) as remote, zipfile.ZipFile(remote) as archive:
        # Official packages use Windows separators. Compare original header
        # names with only that separator substitution: ZipInfo.filename may
        # sanitize separators/NUL differently across operating systems.
        entries = [m for m in archive.infolist()
                   if m.orig_filename.replace('\\', '/') == selected['member']]
        need(len(entries) == 1, 'xml_member_missing_or_ambiguous')
        member = entries[0]
        need(0 < member.file_size <= MAX_XML and 0 < member.compress_size <= MAX_XML
             and member.file_size/member.compress_size < 200 and not member.flag_bits & 1
             and not stat.S_ISLNK(member.external_attr >> 16)
             and member.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, 'unsafe_xml_archive_member')
        with archive.open(member) as stream:
            xml = stream.read(MAX_XML + 1)
        need(len(xml) == member.file_size, 'xml_member_size_mismatch')
    return manifest_raw, xml, {'range_bytes': reader.range_bytes, 'range_requests': reader.range_requests,
                               'archive_etag': remote.etag, 'full_archive_sha_verified': False}


def load_edition(root, edition_id, registry_sha):
    need(isinstance(edition_id, str) and SHA.fullmatch(edition_id), 'invalid_edition_id')
    folder = root / 'editions' / CAP / edition_id
    raw = read_file(folder / 'edition.json', root, 100000)
    record = json.loads(raw)
    core = record['core']
    need(record['version'] == VERSION and SHA.fullmatch(record['first_observed_manifest_sha256'])
         and digest(canon(core)) == edition_id and core['registry_sha256'] == registry_sha
         and core['chapter'] == CAP and core['attribution'] == ATTRIBUTION
         and core['terms_url'] == TERMS_URL, 'edition_or_registry_binding_mismatch')
    xml = read_file(folder / 'source.xml', root, MAX_XML)
    need(digest(xml) == core['xml_sha256'] and len(xml) == core['xml_bytes'], 'stored_xml_sha_mismatch')
    inspect_xml(xml, core)
    return record, digest(raw)


def save_edition(root, core, xml, manifest_sha):
    for path in (root / 'editions', root / 'editions' / CAP):
        safe_mkdir(path)
    edition_id = digest(canon(core))
    folder = root / 'editions' / CAP / edition_id
    safe_mkdir(folder)
    if (folder / 'edition.json').exists() or (folder / 'edition.json').is_symlink():
        record, record_sha = load_edition(root, edition_id, core['registry_sha256'])
        need(record['core'] == core, 'existing_edition_conflict')
        return edition_id, record_sha
    fd, temp = tempfile.mkstemp(prefix='.incoming-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(xml)
        write_candidate_copy(Path(temp), folder / 'source.xml', core['xml_sha256'])
    finally:
        Path(temp).unlink(missing_ok=True)
    atomic_bundle(folder / 'edition.json', {'version': VERSION, 'core': core,
                  'first_observed_manifest_sha256': manifest_sha})
    return edition_id, digest((folder / 'edition.json').read_bytes())


def run(*, state_root=STATE_ROOT, manifest_raw=None, xml=None, fetch=False, action='plan'):
    result = {'version': VERSION, 'chapter': CAP, 'environment': 'staging', 'status': 'BLOCKED',
              'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'reasons': [], 'action': action, 'network_requested': fetch, 'state_written': False,
              'state_write_attempted': False, 'partial_state_may_exist': False,
              'production_access': False, 'production_write': False, 'drive_write': False,
              'db_access': False, 'model_api_used': False, 'baseline_advanced': False,
              'scheduled_watch': False, 'legal_currentness_verified': False, 'semantic_verified': False}
    try:
        need(action in {'plan', 'initialize-baseline', 'save-candidate'}, 'invalid_action')
        need(not fetch or manifest_raw is None and xml is None, 'mixed_input_modes')
        root = scope(state_root)
        registry_raw = REGISTRY.read_bytes()
        registry, registry_sha = yaml.safe_load(registry_raw), digest(registry_raw)
        base_path = root / 'baseline.json'
        base_raw = read_file(base_path, root, 100000) if base_path.exists() or base_path.is_symlink() else None
        baseline = None
        if base_raw is not None:
            baseline = json.loads(base_raw)
            need(baseline['version'] == VERSION, 'baseline_version_mismatch')
            record, record_sha = load_edition(root, baseline['edition_id'], registry_sha)
            need(record_sha == baseline['edition_record_sha256'], 'baseline_record_sha_mismatch')
            baseline = record['core']
        result['baseline_record_sha256_before'] = digest(base_raw) if base_raw is not None else None
        if fetch:
            manifest_raw, xml, transport = fetch_official(registry)
            result['transport'] = transport
        if manifest_raw is None and xml is None:
            need(action == 'plan', 'official_input_required_for_write')
            result['status'] = 'BASELINE_REQUIRED' if baseline is None else 'READY_FOR_OFFICIAL_CHECK'
            return result
        need(isinstance(manifest_raw, bytes) and 0 < len(manifest_raw) <= MAX_MANIFEST, 'manifest_size_invalid')
        selected = identity(json.loads(manifest_raw.decode('utf-8-sig')), registry)
        stats = inspect_xml(xml, selected)
        core = dict(selected, xml_sha256=digest(xml), xml_bytes=len(xml), registry_sha256=registry_sha,
                    attribution=ATTRIBUTION, terms_url=TERMS_URL)
        result.update(edition_id=digest(canon(core)), observed=core, parse_stats=stats,
                      manifest_sha256=digest(manifest_raw), input_provenance='official-https' if fetch else 'operator-supplied')
        status = 'BASELINE_REQUIRED' if baseline is None else 'NO_CHANGE' if core == baseline else 'CHANGED_REVIEW_REQUIRED'
        result['change_reasons'] = ([] if baseline is None else
            [k for k in ('version_date', 'xml_sha256', 'member', 'status_category', 'status_code') if core[k] != baseline[k]])
        need(REGISTRY.read_bytes() == registry_raw, 'registry_changed_during_check')
        fresh = read_file(base_path, root, 100000) if base_path.exists() or base_path.is_symlink() else None
        need(fresh == base_raw, 'baseline_changed_during_check')
        if action == 'initialize-baseline' or action == 'save-candidate' and status == 'CHANGED_REVIEW_REQUIRED':
            need(action != 'initialize-baseline' or baseline is None or baseline == core,
                 'baseline_already_initialized_with_another_edition')
            result.update(state_write_attempted=True, partial_state_may_exist=True)
            safe_mkdir(root)
            lock = root / '.lock'
            lock.mkdir(mode=0o700)
            try:
                need(REGISTRY.read_bytes() == registry_raw, 'registry_changed_before_write')
                locked_base = read_file(base_path, root, 100000) if base_path.exists() or base_path.is_symlink() else None
                need(locked_base == base_raw, 'baseline_changed_before_write')
                edition_id, record_sha = save_edition(root, core, xml, digest(manifest_raw))
                if action == 'initialize-baseline':
                    atomic_bundle(base_path, {'version': VERSION, 'edition_id': edition_id,
                                              'edition_record_sha256': record_sha})
                    status = 'BASELINE_INITIALIZED' if base_raw is None else 'BASELINE_ALREADY_INITIALIZED'
                result.update(state_written=True, stored_edition_id=edition_id)
                load_edition(root, edition_id, registry_sha)
            finally:
                lock.rmdir()
        after = read_file(base_path, root, 100000) if base_path.exists() or base_path.is_symlink() else None
        need(REGISTRY.read_bytes() == registry_raw, 'registry_changed_after_check')
        need(action == 'initialize-baseline' or after == base_raw, 'baseline_advanced_unexpectedly')
        result.update(status=status, baseline_record_sha256_after=digest(after) if after is not None else None,
                      partial_state_may_exist=False)
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile, ET.ParseError, zlib.error) as exc:
        result.update(status='BLOCKED', reasons=['hkel_check_failed:' + type(exc).__name__])
        if isinstance(exc, WatchRefused):
            result['reasons'] = [str(exc)]
        return result


def check_checkout():
    need(Path(__file__).resolve().parent == Path('/opt/ai-knowledge-staging'), 'staging_checkout_required')
    from beta_stage_monitor_candidate_v1 import check_staging_checkout
    check_staging_checkout(Path(__file__).resolve().parent)


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--fetch-official', action='store_true')
    cli.add_argument('--manifest', type=Path)
    cli.add_argument('--xml', type=Path)
    group = cli.add_mutually_exclusive_group()
    group.add_argument('--initialize-baseline', action='store_true')
    group.add_argument('--save-candidate', action='store_true')
    cli.add_argument('--confirm-staging-write', action='store_true')
    args = cli.parse_args(argv)
    write = args.initialize_baseline or args.save_candidate
    if write != args.confirm_staging_write or write and not args.fetch_official:
        cli.error('writes require --fetch-official and --confirm-staging-write')
    if bool(args.manifest) != bool(args.xml) or args.fetch_official and args.manifest:
        cli.error('use either --fetch-official or both --manifest and --xml')
    try:
        check_checkout()
        scope(STATE_ROOT)
        manifest_raw = read_file(args.manifest, STATE_ROOT/'incoming', MAX_MANIFEST) if args.manifest else None
        xml = read_file(args.xml, STATE_ROOT/'incoming', MAX_XML) if args.xml else None
        action = 'initialize-baseline' if args.initialize_baseline else 'save-candidate' if args.save_candidate else 'plan'
        result = run(manifest_raw=manifest_raw, xml=xml, fetch=args.fetch_official, action=action)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        result = {'status': 'BLOCKED', 'reasons': ['staging_runtime_or_input_refused']}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result['status'] == 'BLOCKED' else 3 if result['status'] in {
        'BASELINE_REQUIRED', 'CHANGED_REVIEW_REQUIRED'} else 0


if __name__ == '__main__':
    sys.exit(main())
