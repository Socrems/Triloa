"""Regressions for the four selected review findings; no network or models."""
import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from triloa import download_hy_model as downloader, ocr, preferences, server, translator
from triloa.nemotron import NemotronSpeechSubtitleRunner, _Translation, MAX_PENDING_FINALS

TMP = Path(__file__).resolve().parents[1] / 'cache' / 'tmp'
TMP.mkdir(parents=True, exist_ok=True)


class FinalQueueTests(unittest.TestCase):
    def test_overflow_keeps_recent_finals_and_reports_skips(self):
        messages = []
        runner = NemotronSpeechSubtitleRunner(on_status=messages.append)
        with patch('triloa.nemotron.time.monotonic', return_value=100):
            for index in range(1000):
                runner._queue_translation(_Translation('en', str(index), index, True, queued_at=100))
        self.assertEqual(len(runner._pending_finals), MAX_PENDING_FINALS)
        self.assertEqual([i.original for i in runner._pending_finals],
                         [str(i) for i in range(1000 - MAX_PENDING_FINALS, 1000)])
        self.assertIn('跳过', messages[-1])

    def test_expired_final_skipped_but_long_fresh_phrase_translated(self):
        results, messages = [], []
        runner = NemotronSpeechSubtitleRunner(on_subtitle=results.append, on_status=messages.append)
        runner._queue_translation(_Translation('en', 'expired', 1, True, queued_at=100))
        # Simulate time passing after enqueue, then a fresh final arriving directly
        # in the consumer queue. Its audio start is old but its final text is fresh.
        runner._pending_finals.append(_Translation('en', 'long fresh phrase', 2, True, queued_at=120))
        runner._stop_translator = True
        with patch('triloa.nemotron.time.monotonic', return_value=120), \
             patch('triloa.nemotron.translate_texts', return_value=['译文']) as translate:
            runner._translation_loop()
        translate.assert_called_once()
        self.assertEqual(translate.call_args.args[0], ['long fresh phrase'])
        self.assertEqual([i.original for i in results], ['long fresh phrase'])
        self.assertTrue(any('跳过' in message for message in messages))

    def test_final_expires_while_waiting_for_shared_translator(self):
        now = [100]
        results, messages = [], []
        runner = NemotronSpeechSubtitleRunner(on_subtitle=results.append, on_status=messages.append)
        runner._queue_translation(_Translation('en', 'waiting final', 1, True, queued_at=100))
        runner._stop_translator = True

        @contextmanager
        def delayed_turn(*args):
            now[0] = 111
            yield

        with patch('triloa.nemotron.time.monotonic', side_effect=lambda: now[0]), \
             patch.object(translator, 'translation_turn', delayed_turn), \
             patch.dict(os.environ, TRILOA_TRANSLATOR='hy'), \
             patch('triloa.hy_mt.translate') as infer:
            runner._translation_loop()
        infer.assert_not_called()
        self.assertFalse(results)
        self.assertTrue(any('跳过' in message for message in messages))
        self.assertEqual(translator._requests, 0)


def layout(blocks):
    return SimpleNamespace(
        boxes=[[[left, top], [right, top], [right, top + 20], [left, top + 20]]
               for text, left, right, top in blocks],
        txts=[text for text, left, right, top in blocks], scores=None)


class ReadingOrderTests(unittest.TestCase):
    def test_spanning_headings_and_footer_keep_body_columns_separate(self):
        blocks = [('Title', 200, 650, 0)]
        blocks += [(f'L{i}', 0, 300, 40 + i * 24) for i in range(3)]
        blocks += [(f'R{i}', 400, 700, 40 + i * 24) for i in range(3)]
        blocks += [('Middle', 0, 700, 130)]
        blocks += [(f'L{i}', 0, 300, 170 + (i - 3) * 24) for i in range(3, 6)]
        blocks += [(f'R{i}', 400, 700, 170 + (i - 3) * 24) for i in range(3, 6)]
        blocks += [('Footer', 0, 700, 270)]
        expected = ['Title', 'L0', 'L1', 'L2', 'R0', 'R1', 'R2', 'Middle',
                    'L3', 'L4', 'L5', 'R3', 'R4', 'R5', 'Footer']
        self.assertEqual(ocr._reading_order(layout(list(reversed(blocks)))).split(), expected)

    def test_plain_columns_single_column_and_stacked_blocks(self):
        with self.subTest('plain columns'):
            blocks = [(f'L{i}', 0, 300, i * 24) for i in range(3)]
            blocks += [(f'R{i}', 400, 700, i * 24) for i in range(3)]
            self.assertEqual(ocr._reading_order(layout(blocks)).split(),
                             ['L0', 'L1', 'L2', 'R0', 'R1', 'R2'])
        with self.subTest('single column'):
            blocks = [(f'S{i}', 0, 700, i * 24) for i in range(6)]
            self.assertEqual(ocr._reading_order(layout(blocks)).split(), [f'S{i}' for i in range(6)])
        with self.subTest('vertically separated fragments are not columns'):
            items = [(i * 24, 20, 0, 300, str(i)) for i in range(3)]
            items += [(100 + i * 24, 20, 400, 700, str(i)) for i in range(3)]
            self.assertEqual(len(ocr._column_groups(items)), 1)


class DownloadTests(unittest.TestCase):
    def test_last_byte_and_partial_parent_resume_without_path_collision(self):
        # The one-byte tail reproduces the finding; the other case reuses an
        # existing parent chunk and resumes its missing child segments.
        for prefix, partial_parent in ((15, False), (0, True)):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory(dir=TMP) as directory:
                root = Path(directory)
                destination = root / 'models' / 'hy-mt' / downloader.NAME
                destination.parent.mkdir(parents=True)
                destination.write_bytes(b'x' * prefix)
                if partial_parent:
                    parent = root / 'downloads' / 'hy_parts' / '0-1.part'
                    parent.parent.mkdir(parents=True)
                    parent.write_bytes(b'x')
                downloaded = []

                def fake_download(start, end, path):
                    downloaded.append(path)
                    path.write_bytes(b'x' * (end - start + 1))
                    return path

                digest = sha256(b'x' * 16).hexdigest()
                with patch.multiple(downloader, MODELS=root / 'models', DOWNLOADS=root / 'downloads',
                                    SIZE=16, SHA256=digest), \
                     patch.object(downloader, 'configure_paths'), \
                     patch.object(downloader, '_download_part', side_effect=fake_download) as download, \
                     patch('builtins.print'):
                    downloader.main()
                    self.assertEqual(destination.read_bytes(), b'x' * 16)
                    self.assertEqual(destination.with_suffix('.verified').read_text(), digest)
                    self.assertTrue(all(path.parent.name == 'segments' for path in downloaded))
                    self.assertFalse(list((root / 'downloads').rglob('*.part')))
                    download.reset_mock()
                    downloader.main()
                    download.assert_not_called()


class ModelIdentityTests(unittest.TestCase):
    def test_switch_and_restart_change_identity_and_session_releases_after_error(self):
        with tempfile.TemporaryDirectory(dir=TMP) as directory, \
             patch.object(preferences, 'DATA', Path(directory)), patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / 'qwen-test.gguf'
            path.write_bytes(b'GGUFtest')
            translator.set_backend('hy')
            hy_id = translator.model_identity()
            self.assertEqual(hy_id, translator.model_identity())
            translator.set_backend('qwen', path)
            qwen_id = translator.model_identity()
            self.assertNotEqual(hy_id, qwen_id)
            with patch.object(translator, '_model_instance', 'another process'):
                self.assertNotEqual(qwen_id, translator.model_identity())
            with self.assertRaisesRegex(RuntimeError, 'test failure'):
                with translator.model_session() as identity:
                    self.assertEqual(identity, qwen_id)
                    with self.assertRaises(RuntimeError):
                        translator.set_backend('hy')
                    raise RuntimeError('test failure')
            self.assertEqual(translator._sessions, 0)
            translator.set_backend('hy')
            self.assertNotEqual(hy_id, translator.model_identity())

    def test_health_and_translate_return_consistent_model_identity(self):
        with tempfile.TemporaryDirectory(dir=TMP) as directory, \
             patch.object(preferences, 'DATA', Path(directory)), patch.dict(os.environ, {}, clear=True):
            translator.set_backend('hy')

            def request(method, path, payload=None):
                handler = server.Handler.__new__(server.Handler)
                data = json.dumps(payload).encode() if payload is not None else b''
                handler.path = path
                handler.headers = {'Content-Length': str(len(data))}
                handler.rfile, handler.wfile = io.BytesIO(data), io.BytesIO()
                with patch.object(handler, '_headers') as headers:
                    getattr(handler, method)()
                return headers.call_args.args[0], json.loads(handler.wfile.getvalue())

            status, health = request('do_GET', '/health')
            self.assertEqual(status, 200)

            def translate(texts, source, target):
                with self.assertRaises(RuntimeError):
                    translator.set_backend('auto')
                return ['你好']

            with patch.object(server, 'translate_texts', side_effect=translate):
                status, result = request('do_POST', '/translate', {'texts': ['hello']})
            self.assertEqual(status, 200)
            self.assertEqual(result, {'translations': ['你好'], 'model_id': health['model_id']})
            self.assertEqual(translator._sessions, 0)


if __name__ == '__main__':
    unittest.main()
