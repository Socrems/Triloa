"""Regression tests for cancellation, shared inference and desktop state (no models loaded)."""
import os
import tempfile
from pathlib import Path
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
_root = Path(__file__).resolve().parents[1]
(_root / 'cache' / 'tmp').mkdir(parents=True, exist_ok=True)
_temp = tempfile.TemporaryDirectory(dir=_root / 'cache' / 'tmp')
os.environ['TRILOA_DATA_DIR'] = _temp.name
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor
from triloa import translator as t, preferences
from triloa.desktop import MainWindow, TranslateWorker
from triloa.subtitle_history import SubtitleHistoryOverlay
from triloa.subtitles import SubtitleControl
from triloa.speech import SpeechSubtitle
from triloa.desktop_integration import decode_shortcut, InstanceGuard

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)

class TranslationTests(unittest.TestCase):
    def setUp(self):
        t._cache.clear()

    def test_cancel_discards_inflight_result_and_remaining_chunks(self):
        cancel = threading.Event()
        calls = []
        def fake(text, cancel=None):
            calls.append(text)
            cancel.set()
            return '译文'
        with patch.dict(os.environ, TRILOA_TRANSLATOR='hy'), patch('triloa.hy_mt.translate', fake):
            with self.assertRaises(t.TranslationCancelled):
                t.translate_texts(['A'*500], cancel=cancel)
        self.assertEqual(len(calls), 1)
        self.assertFalse(t._active)
        self.assertEqual(t._requests, 0)
        self.assertFalse(t._cache)

    def test_repeated_content_cached(self):
        with patch.dict(os.environ, TRILOA_TRANSLATOR='hy'), patch('triloa.hy_mt.translate', return_value='你好') as infer:
            self.assertEqual(t.translate_texts(['hello','hello']), ['你好','你好'])
            self.assertEqual(infer.call_count, 1)

    def test_prepare_rewarms_after_cached_result(self):
        with patch.dict(os.environ, TRILOA_TRANSLATOR='hy'), patch('triloa.hy_mt.translate', return_value='你好') as infer:
            t.prepare_translator()
            t.prepare_translator()
            self.assertEqual(infer.call_count, 2)

    def test_priority_queue_and_cancelled_waiter(self):
        order = []
        cancel = threading.Event()
        def wait(name, priority, token=None):
            try:
                with t.translation_turn(priority, token):
                    order.append(name)
            except t.TranslationCancelled:
                pass
        threads = [threading.Thread(target=wait, args=args) for args in [('normal',10),('speech',0),('cancel',0,cancel)]]
        with t.translation_turn():
            for thread in threads: thread.start()
            deadline = time.monotonic() + 2
            while len(t._waiting) < 3 and time.monotonic() < deadline: time.sleep(.01)
            self.assertEqual(len(t._waiting), 3)
            cancel.set()
        for thread in threads: thread.join(2)
        self.assertEqual(order, ['speech','normal'])
        self.assertFalse(t._waiting)

    def test_release_does_not_interrupt_other_feature(self):
        with patch('triloa.hy_mt.stop_owned_server') as stop:
            with t.translation_turn(): t.release_translator()
            stop.assert_not_called()
            t.release_translator()
            stop.assert_called_once()

class DesktopTests(unittest.TestCase):
    def setUp(self):
        (preferences.DATA / 'preferences.json').unlink(missing_ok=True)

    def tearDown(self):
        for widget in app.topLevelWidgets(): widget.close()
        app.processEvents()

    def test_history_keeps_selection_and_clear_all(self):
        h = SubtitleHistoryOverlay(); h.show()
        h.add_final('Original '*100, '译文'*100); app.processEvents()
        cursor = h.text.textCursor(); cursor.setPosition(3); cursor.setPosition(15,QTextCursor.KeepAnchor); h.text.setTextCursor(cursor)
        before = h.text.toPlainText(); selection = h.text.textCursor().selectedText()
        h.add_final('new', '新')
        self.assertEqual(h.text.toPlainText(), before)
        self.assertEqual(h.text.textCursor().selectedText(), selection)
        self.assertEqual(h._unread, 1)
        h.new_button.click()
        self.assertIn('new', h.text.toPlainText())
        h.clear_button.click()
        self.assertEqual(h._entries, [])
        self.assertFalse(h.clear_button.isEnabled())
        h.add_final('again','再次'); self.assertTrue(h.clear_button.isEnabled())

    def test_small_subtitle_page_scrolls_without_squeezing_controls(self):
        from PySide6.QtWidgets import QScrollArea
        from triloa.ui_style import apply_app_style
        apply_app_style(app)
        w=MainWindow(); w.resize(800,580); w.show(); w.tabs.setCurrentIndex(2)
        app.processEvents(); app.processEvents()
        scroll=w.tabs.widget(2)
        self.assertIsInstance(scroll,QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum(),0)
        c=w._subtitle_control
        self.assertLess(c.model_selector.geometry().bottom(),c.model_detail.geometry().top())

    def test_history_chronological_and_bottom_follow(self):
        h = SubtitleHistoryOverlay(); h.resize(400, 230); h.show()
        for i in range(5): h.add_final(f'entry-{i} ' + 'text '*60, '译文'*50)
        app.processEvents()
        content=h.text.toPlainText()
        self.assertLess(content.index('entry-0'), content.index('entry-4'))
        bar=h.text.verticalScrollBar()
        self.assertEqual(bar.value(),bar.maximum())
        bar.setValue(0); before=h.text.toPlainText()
        h.add_final('newest','最新')
        self.assertEqual(h.text.toPlainText(),before)
        h.new_button.click(); app.processEvents()
        self.assertTrue(h.text.toPlainText().rstrip().endswith('最新'))
        self.assertEqual(bar.value(),bar.maximum())

    def test_subtitle_vertical_edges_resize_and_lock(self):
        from triloa.subtitles import SubtitleOverlay
        from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
        from PySide6.QtGui import QMouseEvent
        w=SubtitleOverlay(); w.setGeometry(60,200,650,250); w.show(); app.processEvents()
        if w._locked: w._toggle_locked()
        handle=w._height_handles[0]
        def send(kind, point, button, buttons):
            event=QMouseEvent(kind, QPointF(20,3), QPointF(point),button,buttons,Qt.NoModifier)
            QApplication.sendEvent(handle,event)
        origin=handle.mapToGlobal(handle.rect().center())
        bottom=w.geometry().bottom()
        send(QEvent.MouseButtonPress,origin,Qt.LeftButton,Qt.LeftButton)
        send(QEvent.MouseMove,origin+QPoint(0,-90),Qt.NoButton,Qt.LeftButton)
        send(QEvent.MouseButtonRelease,origin,Qt.LeftButton,Qt.NoButton)
        self.assertEqual(w.height(),340)
        self.assertEqual(w.width(),650)
        self.assertEqual(w.geometry().bottom(),bottom)
        w.resize(650,150); app.processEvents()
        self.assertEqual(w.height(),150)
        w._toggle_locked()
        self.assertTrue(all(h.isHidden() for h in w._height_handles))

    def test_geometry_lock_restore_and_invalid_settings(self):
        preferences.put('window.history', {'rect':[90000,90000,460,340], 'locked':False})
        h=SubtitleHistoryOverlay(); h.show(); app.processEvents()
        self.assertFalse(h._locked)
        self.assertTrue(app.primaryScreen().availableGeometry().intersects(h.geometry()))
        h.window_state.save()
        restored=SubtitleHistoryOverlay()
        self.assertTrue(restored.window_state.restored)
        self.assertFalse(restored._locked)
        (preferences.DATA/'preferences.json').write_text('{bad', encoding='utf-8')
        self.assertEqual(preferences.get('missing','fallback'), 'fallback')

    def test_failed_monitor_not_cached_and_manual_retry(self):
        w=MainWindow()
        w._monitoring=True; w._monitor_candidate_hash='candidate'; w._monitor_last_hash=None
        w._failure('test failure', True, w._monitor_generation)
        self.assertIsNone(w._monitor_last_hash)
        self.assertGreater(w._monitor_retry_at,time.monotonic())
        w._task_in_flight=True; w.retry_monitor()
        w._monitor_last_hash='candidate'
        w._worker_finished()
        self.assertIsNone(w._monitor_last_hash)
        self.assertEqual(w._monitor_retry_at,0)

    def test_cancelled_gui_result_ignored(self):
        w=MainWindow(); w.translation.setPlainText('existing')
        worker=TranslateWorker(text='new'); w._worker=worker; worker.cancel_event.set()
        w._complete('new','stale')
        self.assertEqual(w.translation.toPlainText(),'existing')
        w._worker=None

    def test_history_independent_of_caption_visibility(self):
        c=SubtitleControl(embedded=True); c.runner=object(); c._display_enabled=True
        c.toggle_overlay()
        c._display_subtitle(SpeechSubtitle('en','hello','你好',0,True))
        self.assertFalse(c.overlay.isVisible()); self.assertEqual(len(c.history._entries),1)
        c.runner=None; c.close()

    def test_shortcuts_and_single_instance(self):
        self.assertEqual(decode_shortcut('Ctrl+Alt+T'), (0x4003,ord('T')))
        for text in ('T','Ctrl+A, Ctrl+B','Ctrl+Left'):
            with self.assertRaises(ValueError): decode_shortcut(text)
        guard=InstanceGuard(); other=InstanceGuard()
        try:
            self.assertTrue(guard.acquire()); self.assertFalse(other.acquire())
        finally: guard.close()

class StreamingModeTests(unittest.TestCase):
    def setUp(self):
        (preferences.DATA / 'preferences.json').unlink(missing_ok=True)
        t._cache.clear()

    def test_stable_prefix_and_no_repeated_translation(self):
        from triloa.stable_phrase import StablePhrase
        stable = StablePhrase()
        stable.observe('Please turn left at', 0)
        self.assertIsNone(stable.poll(.2))
        stable.observe('Please turn left at the next', .2)
        self.assertEqual(stable.poll(.5), 'Please turn left at')
        self.assertIsNone(stable.poll(.6))
        self.assertEqual(stable.poll(2), 'Please turn left at the next')
        self.assertIsNone(stable.poll(4))

    def test_japanese_timeout_and_correction(self):
        from triloa.stable_phrase import StablePhrase
        stable = StablePhrase()
        stable.observe('今日は', 0)
        self.assertIsNone(stable.poll(.5))
        self.assertEqual(stable.poll(1.5), '今日は')
        stable.observe('昨日は雨でした。', 1.6)
        stable.observe('昨日は雨でした。', 1.8)
        self.assertEqual(stable.poll(2.1), '昨日は雨でした。')

    def test_new_tokens_do_not_inherit_old_stability(self):
        from triloa.stable_phrase import StablePhrase
        stable = StablePhrase()
        stable.observe('one two three four', 0)
        stable.observe('one two three four five six seven', .5)
        stable.observe('one two three four five six seven eight', .6)
        self.assertEqual(stable.poll(.61), 'one two three four')

    def test_model_switch_locked_during_session_and_request(self):
        t.begin_subtitle_session()
        try:
            with self.assertRaises(RuntimeError): t.set_backend('auto')
        finally: t.end_subtitle_session()
        with t.translation_turn():
            with self.assertRaises(RuntimeError): t.set_backend('auto')
        t.set_backend('auto')

    def test_model_cache_separation_and_explicit_qwen_failure(self):
        path = preferences.DATA / 'Qwen3-test.gguf'
        path.write_bytes(b'GGUFtest')
        with patch.dict(os.environ, {}, clear=True), patch('triloa.hy_mt.translate', return_value='混元') as infer:
            t.set_backend('hy')
            self.assertEqual(t.translate_texts(['hello']), ['混元'])
            t.set_backend('qwen', str(path))
            infer.return_value='通义'
            self.assertEqual(t.translate_texts(['hello']), ['通义'])
            self.assertEqual(infer.call_args.kwargs['backend'], 'qwen')
            infer.side_effect=RuntimeError('qwen failed')
            with self.assertRaises(RuntimeError): t.translate_texts(['another'])
        self.assertEqual(t._requests, 0)

    def test_obsolete_draft_never_reaches_model(self):
        with patch.dict(os.environ, TRILOA_TRANSLATOR='hy'), patch('triloa.hy_mt.translate') as infer:
            with self.assertRaises(t.TranslationCancelled):
                t.translate_texts(['obsolete'], is_obsolete=lambda: True)
            infer.assert_not_called()
        self.assertEqual(t._requests, 0)

    def test_final_replaces_pending_draft_and_bypasses_cache(self):
        from triloa.nemotron import NemotronSpeechSubtitleRunner, _Translation
        results=[]
        runner=NemotronSpeechSubtitleRunner(on_subtitle=results.append)
        runner._queue_translation(_Translation('en','partial',1,False))
        runner._queue_translation(_Translation('en','complete sentence',1,True))
        self.assertIsNone(runner._pending_draft)
        runner._stop_translator=True
        with patch('triloa.nemotron.translate_texts',return_value=['完整译文']) as translate:
            runner._translation_loop()
            self.assertFalse(translate.call_args.kwargs['use_cache'])
        self.assertEqual(len(results),1)
        self.assertTrue(results[0].final)
        self.assertEqual(results[0].original,'complete sentence')

if __name__ == '__main__':
    unittest.main()
