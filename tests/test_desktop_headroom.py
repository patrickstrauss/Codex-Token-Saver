import hashlib
import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_headroom import DesktopHeadroom


class MemoryCache:
    def __init__(self):
        self.entries = {}

    def store(self, original, compressed, **kwargs):
        key = hashlib.sha256(original.encode('utf-8')).hexdigest()[:24]
        self.entries[key] = SimpleNamespace(original_content=original)
        return key

    def retrieve(self, key):
        return self.entries.get(key)


class DesktopHeadroomTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.cache = MemoryCache()
        self.backend = self.make_backend()

    def make_backend(self, **kwargs):
        options = dict(compressor=lambda text: 'Short overview.', token_counter=len, cache=self.cache)
        options.update(kwargs)
        return DesktopHeadroom(self.root / 'state', **options)

    def write(self, text, name='source.txt'):
        file = self.root / name
        file.write_bytes(text.encode('utf-8'))
        return file

    def payload(self, result):
        return result.split('\n\n', 1)[1]

    def test_construction_and_empty_stats_do_not_import_headroom_or_tokenizer(self):
        with patch('desktop_headroom.importlib.import_module', side_effect=AssertionError('eager import')):
            backend = DesktopHeadroom(self.root / 'lazy-state')
            self.assertEqual(backend.stats()['read_count'], 0)

    def test_read_returns_compressed_overview_with_retrieval_key(self):
        original = 'long repetitive log entry\n' * 100
        file = self.write(original)
        result = self.backend.read_file(str(file))
        key = hashlib.sha256(original.encode()).hexdigest()[:24]
        self.assertIn('compressed overview', result.lower())
        self.assertIn(key, result)
        self.assertIn('retrieve', result.lower())
        self.assertEqual(self.payload(result), 'Short overview.')
        self.assertEqual(self.cache.retrieve(key).original_content, original)

    def test_original_is_immutable_when_compressor_returns_changed_text(self):
        text = 'CRITICAL exact original\r\n' * 100
        file = self.write(text)
        result = self.backend.read_file(str(file))
        key = hashlib.sha256(text.encode()).hexdigest()[:24]
        self.assertEqual(self.payload(self.backend.retrieve(key)), text)
        self.assertEqual(file.read_bytes(), text.encode())

    def test_disabled_compression_preserves_crlf_and_last_line(self):
        text = 'alpha\r\nbeta\nfinal'
        file = self.write(text)
        result = self.backend.read_file(str(file), compress=False)
        self.assertEqual(self.payload(result), text)
        self.assertFalse(self.cache.entries)

    def test_window_preserves_line_endings_and_caches_full_original(self):
        text = 'first\r\n' + ('long middle text ' * 250) + '\r\nlast'
        file = self.write(text)
        self.backend.read_file(str(file), start_line=2, max_lines=1)
        key = hashlib.sha256(text.encode()).hexdigest()[:24]
        self.assertEqual(self.payload(self.backend.retrieve(key, start_line=3, max_lines=1)), 'last')
        self.assertEqual(self.payload(self.backend.retrieve(key, start_line=1, max_lines=1)), 'first\r\n')

    def test_inflated_compression_returns_original(self):
        backend = self.make_backend(compressor=lambda text: text * 2)
        text = 'row ' * 100
        result = backend.read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertFalse(self.cache.entries)

    def test_compressed_header_overhead_cannot_waste_more_than_raw_header(self):
        backend = self.make_backend(compressor=lambda text: text[:-1])
        text = 'row ' * 100
        result = backend.read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertFalse(self.cache.entries)

    def test_compression_failure_returns_original_with_notice(self):
        def broken(_):
            raise RuntimeError('fixture failure')
        text = 'row ' * 100
        result = self.make_backend(compressor=broken).read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertIn('compression unavailable', result.lower())

    def test_invalid_compressor_response_returns_original_with_notice(self):
        text = 'row ' * 100
        result = self.make_backend(compressor=lambda _: None).read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertIn('compression unavailable', result.lower())

    def test_empty_compressor_response_returns_original_with_notice(self):
        text = 'row ' * 100
        result = self.make_backend(compressor=lambda _: '').read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertIn('compression unavailable', result.lower())

    def test_cache_failure_never_returns_unrecoverable_compression(self):
        with patch.object(self.cache, 'store', side_effect=OSError('cache unavailable')):
            text = 'row ' * 1000
            result = self.backend.read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertIn('original', result.lower())

    def test_silent_cache_write_failure_returns_original(self):
        text = 'row ' * 1000
        key = hashlib.sha256(text.encode()).hexdigest()[:24]
        with patch.object(self.cache, 'store', return_value=key):
            result = self.backend.read_file(str(self.write(text)))
        self.assertEqual(self.payload(result), text)
        self.assertIn('original', result.lower())

    def test_full_returned_text_is_counted_in_signed_savings(self):
        text = 'row ' * 1000
        result = self.backend.read_file(str(self.write(text)))
        stats = self.backend.stats()
        self.assertEqual(stats['total_saved'], len(text) - len(result))
        self.assertEqual(stats['gross_saved'], len(text) - len(result))
        self.assertEqual(stats['read_count'], 1)
        self.assertEqual(stats['retrieve_count'], 0)
        self.assertTrue(stats['last_recorded_at'])

    def test_retrieval_debits_all_returned_tokens(self):
        text = 'row ' * 1000
        compressed = self.backend.read_file(str(self.write(text)))
        key = hashlib.sha256(text.encode()).hexdigest()[:24]
        recovered = self.backend.retrieve(key)
        stats = self.backend.stats()
        self.assertEqual(stats['total_saved'], len(text) - len(compressed) - len(recovered))
        self.assertEqual(stats['gross_saved'], len(text) - len(compressed))
        self.assertEqual(stats['retrieval_tokens'], len(recovered))
        self.assertEqual(stats['retrieve_count'], 1)

    def test_uncompressed_read_can_report_negative_net_savings(self):
        text = 'tiny'
        result = self.backend.read_file(str(self.write(text)), compress=False)
        stats = self.backend.stats()
        self.assertEqual(stats['total_saved'], len(text) - len(result))
        self.assertLess(stats['total_saved'], 0)
        self.assertEqual(stats['gross_saved'], 0)

    def test_window_input_count_counts_only_selected_content(self):
        text = 'line one\r\nline two\r\nline three'
        result = self.backend.read_file(str(self.write(text)), start_line=2, max_lines=1, compress=False)
        self.assertEqual(self.payload(result), 'line two\r\n')
        self.assertEqual(self.backend.stats()['total_saved'], len('line two\r\n') - len(result))

    def test_database_persists_across_backend_restart(self):
        self.backend.read_file(str(self.write('text')), compress=False)
        self.assertEqual(self.make_backend().stats(), self.backend.stats())
        with closing(sqlite3.connect(self.root / 'state' / 'activity.db')) as connection:
            self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(connection.execute('SELECT kind FROM events').fetchone()[0], 'read')

    def test_concurrent_writers_keep_all_events(self):
        file = self.write('tiny')
        def run(_):
            return self.make_backend().read_file(str(file), compress=False)
        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(run, range(24)))
        self.assertEqual(self.backend.stats()['read_count'], 24)
        self.assertEqual(self.backend.stats()['total_saved'], sum(4 - len(output) for output in outputs))

    def test_relative_path_rejected(self):
        with self.assertRaises(ValueError):
            self.backend.read_file('relative.txt')

    def test_directory_rejected(self):
        with self.assertRaises((ValueError, IsADirectoryError)):
            self.backend.read_file(str(self.root))

    def test_invalid_utf8_and_null_rejected(self):
        for data in (b'\xff\xfe', b'text\x00binary'):
            with self.subTest(data=data):
                file = self.root / 'binary.txt'
                file.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.backend.read_file(str(file))
        self.assertEqual(self.backend.stats()['read_count'], 0)

    def test_oversize_file_rejected(self):
        file = self.root / 'large.txt'
        file.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.backend.read_file(str(file))

    def test_bad_line_parameters_rejected_for_reads_and_retrieval(self):
        text = 'long line\n' * 1000
        file = self.write(text)
        self.backend.read_file(str(file))
        key = hashlib.sha256(text.encode()).hexdigest()[:24]
        for kwargs in ({'start_line': 0}, {'start_line': -1}, {'start_line': 1001},
                       {'max_lines': 0}, {'max_lines': -1}, {'max_lines': 10001},
                       {'start_line': True}, {'max_lines': 1.5}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.backend.read_file(str(file), **kwargs)
                with self.assertRaises(ValueError):
                    self.backend.retrieve(key, **kwargs)

    def test_empty_file_is_readable_at_first_line_only(self):
        file = self.write('')
        self.assertEqual(self.payload(self.backend.read_file(str(file), compress=False)), '')
        with self.assertRaises(ValueError):
            self.backend.read_file(str(file), start_line=2)

    def test_invalid_and_missing_hash_are_explicit_errors(self):
        for key in ('../escape', '', 'abc', 'z' * 24):
            with self.assertRaises(ValueError):
                self.backend.retrieve(key)
        with self.assertRaises(LookupError):
            self.backend.retrieve('a' * 24)
        self.assertEqual(self.backend.stats()['retrieve_count'], 0)

    def test_stats_state_estimates_not_billing(self):
        stats = self.backend.stats()
        self.assertTrue(stats['estimated'])
        self.assertEqual(stats['tokenizer'], 'o200k_base')


@unittest.skipUnless(importlib.util.find_spec('headroom') is not None, 'Headroom runtime required')
class RealHeadroomTests(unittest.TestCase):
    def test_offline_sdk_and_persistent_retrieval_in_fresh_process(self):
        root = Path(__file__).resolve().parents[1]
        script = r'''
import hashlib,json,socket,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
def denied(*args,**kwargs): raise AssertionError('Unexpected network access')
socket.socket.connect=denied
from desktop_headroom import DesktopHeadroom
folder=Path(sys.argv[2])
backend=DesktopHeadroom(folder/'state')
if sys.argv[3]=='read':
    text=json.dumps({'records':[{'id':i,'level':'ERROR' if i==78 else 'INFO','message':'CRITICAL_DB_FAILURE E78' if i==78 else 'completed successfully','service':'api'} for i in range(150)]})
    file=folder/'source.json'
    file.write_bytes(text.encode())
    result=backend.read_file(str(file))
    assert 'compressed overview' in result.lower(), result[:300]
    assert 'CRITICAL_DB_FAILURE E78' in result
    assert backend.stats()['total_saved']>0
    print(json.dumps({'hash':hashlib.sha256(text.encode()).hexdigest()[:24],'stats':backend.stats()}))
else:
    text=(folder/'source.json').read_bytes().decode()
    key=hashlib.sha256(text.encode()).hexdigest()[:24]
    result=backend.retrieve(key)
    assert result.split('\n\n',1)[1]==text
    print(json.dumps({'exact_retrieval':True,'stats':backend.stats()}))
'''
        with tempfile.TemporaryDirectory() as temp:
            env = dict(os.environ, HEADROOM_WORKSPACE_DIR=str(Path(temp) / 'state'), HEADROOM_OFFLINE='1',
                       HEADROOM_TELEMETRY='off', HEADROOM_LOG_PAYLOAD_PREVIEW='0',
                       TIKTOKEN_CACHE_DIR=str(root / 'headroom' / 'tokenizer-cache'))
            read = subprocess.run([sys.executable, '-c', script, str(root), temp, 'read'],
                                  env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(read.returncode, 0, read.stderr)
            first = json.loads(read.stdout)
            retrieve = subprocess.run([sys.executable, '-c', script, str(root), temp, 'retrieve'],
                                      env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(retrieve.returncode, 0, retrieve.stderr)
            second = json.loads(retrieve.stdout)
            self.assertTrue(second['exact_retrieval'])
            self.assertEqual(second['stats']['read_count'], 1)
            self.assertEqual(second['stats']['retrieve_count'], 1)
            self.assertLess(second['stats']['total_saved'], first['stats']['total_saved'])


@unittest.skipUnless(importlib.util.find_spec('tiktoken') is not None, 'Tokenizer runtime required')
class OfflineTokenizerTests(unittest.TestCase):
    def run_probe(self, mode):
        root = Path(__file__).resolve().parents[1]
        script = r'''
import json,os,shutil,sys
from pathlib import Path
from unittest.mock import Mock
import requests
requests.get=Mock(side_effect=AssertionError('Network download forbidden'))
sys.path.insert(0,sys.argv[1])
folder=Path(sys.argv[2])
cache=folder/'cache'
cache.mkdir()
os.environ['TIKTOKEN_CACHE_DIR']=str(cache)
os.environ['HEADROOM_WORKSPACE_DIR']=str(folder/'state')
key='fb374d419588a4632f3f557e76b4b70aebbca790'
mode=sys.argv[3]
if mode=='corrupt':
    (cache/key).write_bytes(b'not the tokenizer vocabulary')
elif mode=='valid':
    shutil.copyfile(Path(sys.argv[1])/'headroom/tokenizer-cache'/key,cache/key)
    import tiktoken_ext.openai_public as public
    public.load_tiktoken_bpe=Mock(side_effect=AssertionError('Download-capable loader forbidden'))
from desktop_headroom import DesktopHeadroom
backend=DesktopHeadroom(folder/'state')
file=folder/'sample.txt'
file.write_bytes(b'hello world')
if mode=='valid':
    result=backend.read_file(str(file),compress=False)
    assert result.endswith('hello world')
    assert backend.stats()['read_count']==1
    # The SDK must reuse the same validated in-memory encoding, even if the
    # cache changes later. No download-capable constructor may run.
    (cache/key).unlink()
    import tiktoken
    assert tiktoken.get_encoding('o200k_base').encode('hello world')==[24912,2375]
    # Only o200k was ever present; compression also must remain fully local,
    # including any other tokenizer a transform might attempt to load.
    text=json.dumps({'records':[{'id':i,'level':'ERROR' if i==78 else 'INFO','message':'CRITICAL_E78' if i==78 else 'completed successfully','service':'api'} for i in range(150)]})
    file.write_bytes(text.encode())
    result=backend.read_file(str(file))
    assert 'compressed overview' in result.lower()
    assert 'CRITICAL_E78' in result
    assert backend.stats()['gross_saved']>0
    public.load_tiktoken_bpe.assert_not_called()
    import tiktoken.load as token_load
    assert token_load.read_file(str(file))==text.encode()
    for url in ('https://example.invalid/cl100k_base.tiktoken','http://example.invalid/vocabulary','gs://bucket/vocabulary'):
        try:
            token_load.read_file(url)
        except RuntimeError as error:
            assert 'native' in str(error).lower()
        else:
            raise AssertionError('Remote tokenizer fallback must be rejected')
else:
    try:
        backend.read_file(str(file),compress=False)
    except RuntimeError as error:
        assert 'tokenizer' in str(error).lower()
        assert 'native' in str(error).lower()
    else:
        raise AssertionError('Missing/corrupt tokenizer must be an explicit tool error')
    assert backend.stats()['read_count']==0
    assert backend.stats()['total_saved']==0
requests.get.assert_not_called()
print(json.dumps({'mode':mode,'network_calls':requests.get.call_count}))
'''
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, HEADROOM_OFFLINE='1', HEADROOM_TELEMETRY='off')
            probe = subprocess.run([sys.executable, '-c', script, str(root), folder, mode], env=env,
                                   capture_output=True, text=True, timeout=15)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(json.loads(probe.stdout)['network_calls'], 0)

    def test_missing_tokenizer_cache_never_downloads_or_records_savings(self):
        self.run_probe('missing')

    def test_corrupt_tokenizer_cache_never_downloads_or_records_savings(self):
        self.run_probe('corrupt')

    def test_valid_local_encoding_never_uses_download_loader_and_is_reusable(self):
        self.run_probe('valid')


if __name__ == '__main__':
    unittest.main()
