"""Exercise real HTTP transfers and the resource dialog, without model downloads."""
from dataclasses import replace
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from triloa import preferences
from triloa.resource_setup import ResourceSetupDialog
from triloa.resources import InstallationCancelled, Resource, ResourceError, ResourceManager
from triloa.paths import configure_paths

configure_paths()

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
TMP = Path(__file__).resolve().parents[1] / 'cache/tmp'
TMP.mkdir(parents=True, exist_ok=True)


class Transfers(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(dir=TMP, prefix='resources-test-')
        self.root = Path(self.temporary.name)
        self.payload = b'model fixture\n' * 50000
        self.requests = []
        self.mode = 'normal'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                offset = int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
                owner.requests.append(offset)
                if owner.mode == 'fail':
                    self.send_error(503)
                    return
                if owner.mode == 'ignore':
                    offset = 0
                data = owner.payload[offset:]
                self.send_response(206 if offset else 200)
                self.send_header('Content-Length', str(len(data)))
                if offset:
                    self.send_header('Content-Range', f'bytes {offset}-{len(owner.payload)-1}/{len(owner.payload)}')
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.resource = Resource('fixture', 'fixture model', 'basic', f'http://127.0.0.1:{self.server.server_port}/model', 'fixture.bin', len(self.payload), sha256(self.payload).hexdigest())
        self.manager = ResourceManager(models=self.root/'models', data=self.root/'data', downloads=self.root/'downloads', root=self.root, resources=(self.resource,), legacy=False)
        self.preference_patch = patch.object(preferences, 'DATA', self.root/'data')
        self.preference_patch.start()

    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.deleteLater()
        app.processEvents()
        self.preference_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def partial(self, amount):
        self.manager.downloads.mkdir()
        (self.manager.downloads/'fixture.part').write_bytes(self.payload[:amount])

    def test_resume_and_skip_after_install(self):
        self.partial(10000)
        events = []
        self.manager.install(('basic',), Event(), events.append)
        self.assertEqual(self.requests, [10000])
        self.assertEqual((self.manager.models/'fixture.bin').read_bytes(), self.payload)
        self.manager.install(('basic',), Event(), events.append)
        self.assertEqual(self.requests, [10000])
        self.assertTrue(any(e['phase']=='verify' for e in events))

    def test_server_ignoring_range_restarts_cleanly(self):
        self.mode = 'ignore'
        self.partial(12345)
        self.manager.install(('basic',), Event())
        self.assertEqual((self.manager.models/'fixture.bin').read_bytes(), self.payload)

    def test_bad_checksum_is_rejected_then_manual_retry_succeeds(self):
        self.payload = b'x' * len(self.payload)
        with patch('triloa.resources.Event.wait', return_value=False):
            with self.assertRaises(ResourceError):
                self.manager.install(('basic',), Event())
        self.assertFalse((self.manager.models/'fixture.bin').exists())
        self.assertFalse((self.manager.downloads/'fixture.part').exists())
        self.payload = b'model fixture\n' * 50000
        self.manager.install(('basic',), Event())
        self.assertTrue(self.manager.ready('basic'))

    def test_cancel_preserves_resume_data(self):
        cancel = Event()
        self.partial(10000)
        cancel.set()
        with self.assertRaises(InstallationCancelled):
            self.manager.install(('basic',), cancel)
        self.assertEqual((self.manager.downloads/'fixture.part').stat().st_size, 10000)
        self.assertFalse((self.manager.models/'fixture.bin').exists())

    def test_argos_extraction_is_atomic_and_rejects_traversal(self):
        def archive(unsafe=False):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as z:
                z.writestr('translate-en_zh-1_9/metadata.json', json.dumps({'from_code':'en','to_code':'zh'}))
                z.writestr('translate-en_zh-1_9/model/model.bin', b'weights')
                z.writestr('translate-en_zh-1_9/sentencepiece.model', b'tokenizer')
                if unsafe:
                    z.writestr('../escaped.txt', 'escape')
            return buffer.getvalue()
        for unsafe in (True, False):
            self.payload = archive(unsafe)
            resource = replace(self.resource, size=len(self.payload), digest=sha256(self.payload).hexdigest(), pair=('en','zh'))
            self.manager.resources = (resource,)
            cache_clear = Mock()
            with patch.dict('sys.modules', {'argostranslate.translate': SimpleNamespace(get_installed_languages=SimpleNamespace(cache_clear=cache_clear))}):
                if unsafe:
                    with self.assertRaises(ResourceError):
                        self.manager.install(('basic',), Event())
                    self.assertFalse((self.manager.downloads/'escaped.txt').exists())
                    self.assertFalse(self.manager.ready('basic'))
                else:
                    self.manager.install(('basic',), Event())
                    self.assertTrue(self.manager.ready('basic'))
                    cache_clear.assert_called_once()

    def test_dialog_failure_retry_and_skip(self):
        self.mode = 'fail'
        with patch('triloa.resource_setup.ResourceManager', return_value=self.manager), patch('triloa.resource_setup.install_resources', side_effect=self.manager.install), patch('triloa.resources.Event.wait', return_value=False):
            dialog = ResourceSetupDialog(first_run=True)
            dialog.show()
            dialog.start_button.click()
            deadline = time.monotonic() + 8
            while dialog.worker and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertIsNone(dialog.worker)
            self.assertEqual(dialog._outcome, 'failed')
            self.assertTrue(dialog.start_button.isEnabled())
            self.mode = 'normal'
            dialog.start_button.click()
            deadline = time.monotonic() + 8
            while dialog.worker and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)
            self.assertIsNone(dialog.worker)
            self.assertEqual(dialog._outcome, 'success')
            dialog.start_button.click()
            self.assertEqual(dialog.result(), 1)
            self.assertTrue(preferences.get('setup.seen'))


if __name__ == '__main__':
    unittest.main()
