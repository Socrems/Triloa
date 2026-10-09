"""Local model management, inference routing and UI regressions without weights."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QDialog
from triloa import hy_mt, preferences, translator as t
from triloa.translation_models import registered_models
from triloa.translation_picker import TranslationModelPicker, LocalModelDialog

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)
TMP = Path(__file__).resolve().parents[1] / 'cache' / 'tmp'
TMP.mkdir(parents=True, exist_ok=True)


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=TMP)
        self.root = Path(self.directory.name)
        self.prefs = patch.object(preferences, 'DATA', self.root)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.prefs.start()
        self.environment.start()
        t._cache.clear()

    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.close()
        app.processEvents()
        self.environment.stop()
        self.prefs.stop()
        self.directory.cleanup()

    def model_file(self, name):
        path = self.root / name
        path.write_bytes(b'GGUFtest')
        return path

    def test_multiple_models_persist_without_copying_or_duplicate_records(self):
        preferences.put('unrelated.setting', 42)
        first = t.save_local_model(self.model_file('one.gguf'), '模型一')
        second = t.save_local_model(self.model_file('two.gguf'), '模型二', 'qwen', 'cpu')
        self.assertEqual(t.model_label(), '模型二')
        self.assertEqual([item.id for item in registered_models()], [first.id, second.id])
        saved = json.loads((self.root / 'preferences.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['unrelated.setting'], 42)
        self.assertEqual(saved['translation.model_id'], second.id)
        self.assertEqual(saved['translation.models'][1]['execution'], 'cpu')
        self.assertEqual(first.path.read_bytes(), b'GGUFtest')
        again = t.save_local_model(first.path, '新名称')
        self.assertEqual(first.id, again.id)
        self.assertEqual(len(registered_models()), 2)

    def test_invalid_file_and_corrupt_records_do_not_replace_valid_selection(self):
        current = t.save_local_model(self.model_file('valid.gguf'))
        before = preferences.read()
        invalid = self.root / 'broken.gguf'
        invalid.write_bytes(b'broken')
        with self.assertRaises(ValueError):
            t.save_local_model(invalid)
        self.assertEqual(preferences.read(), before)
        preferences.put('translation.models', [None, {'id': 'bad', 'name': 'bad', 'path': 'x', 'profile': []}, current.record()])
        self.assertEqual(registered_models(), [current])

    def test_custom_inference_and_cache_follow_the_selected_record(self):
        first = t.save_local_model(self.model_file('generic.gguf'), '通用模型', execution='cpu')
        first_identity = t.model_identity()
        with patch.object(hy_mt, 'translate', return_value='一') as infer:
            self.assertEqual(t.translate_texts(['hello', 'hello']), ['一', '一'])
            infer.assert_called_once()
            self.assertEqual(infer.call_args.kwargs['model'], first.path)
            self.assertEqual(infer.call_args.kwargs['profile'], 'generic')
            self.assertEqual(infer.call_args.kwargs['execution'], 'cpu')
            second = t.save_local_model(self.model_file('Qwen.gguf'), 'Qwen 自选', 'qwen')
            infer.return_value = '二'
            self.assertEqual(t.translate_texts(['hello']), ['二'])
            self.assertEqual(infer.call_args.kwargs['model'], second.path)
            self.assertEqual(infer.call_args.kwargs['profile'], 'qwen')
        self.assertNotEqual(first_identity, t.model_identity())
        self.assertNotIn(str(second.path), t.model_identity())
        t.set_backend('custom', model_id=first.id)
        self.assertEqual(t.model_label(), '通用模型')

    def test_missing_or_failing_model_is_explicit_and_never_falls_back(self):
        model = t.save_local_model(self.model_file('chosen.gguf'))
        with patch.object(hy_mt, 'translate', return_value='译文'):
            t.translate_texts(['cached'])
        model.path.unlink()
        with patch.object(t, '_argos') as fallback, patch.object(hy_mt, 'translate') as infer:
            with self.assertRaisesRegex(RuntimeError, '移动或删除'):
                t.translate_texts(['cached'])
            with self.assertRaises(RuntimeError):
                t.begin_subtitle_session()
            fallback.assert_not_called()
            infer.assert_not_called()
        model.path.write_bytes(b'GGUFtest')
        with patch.object(t, '_argos') as fallback, patch.object(hy_mt, 'translate', side_effect=RuntimeError('unsupported')):
            with self.assertRaisesRegex(RuntimeError, 'unsupported'):
                t.translate_texts(['hello'])
            fallback.assert_not_called()
        self.assertEqual(t.selected_backend(), 'custom')
        self.assertEqual(t._requests, 0)
        self.assertEqual(t._sessions, 0)

    def test_changes_locked_during_subtitle_session_and_inference(self):
        model = t.save_local_model(self.model_file('locked.gguf'))
        def assert_locked():
            for change in [lambda: t.set_backend('argos'), lambda: t.remove_local_model(model.id),
                           lambda: t.save_local_model(model.path, 'changed', model_id=model.id)]:
                with self.assertRaises(RuntimeError):
                    change()
        t.begin_subtitle_session()
        try:
            assert_locked()
        finally:
            t.end_subtitle_session()
        with t.translation_turn():
            assert_locked()
        t.set_backend('argos')
        self.assertEqual(t.selected_backend(), 'argos')

    def test_edit_and_remove_keep_model_files_and_other_records(self):
        one = t.save_local_model(self.model_file('one.gguf'))
        two = t.save_local_model(self.model_file('two.gguf'))
        moved_path = self.model_file('moved.gguf')
        changed = t.save_local_model(moved_path, '改名模型', 'qwen', 'cpu', model_id=one.id)
        self.assertEqual(changed.id, one.id)
        before = preferences.read()
        with self.assertRaises(ValueError):
            t.save_local_model(two.path, model_id=one.id)
        self.assertEqual(preferences.read(), before)
        t.remove_local_model(two.id)
        self.assertEqual(t.selected_backend(), 'custom')
        t.remove_local_model(one.id)
        self.assertEqual(t.selected_backend(), 'auto')
        self.assertTrue(all(path.is_file() for path in (one.path, two.path, moved_path)))
        self.assertFalse(registered_models())

    def test_picker_and_settings_restore_and_lock_shared_choices(self):
        one = t.save_local_model(self.model_file('one.gguf'), '模型一')
        two = t.save_local_model(self.model_file('Qwen.gguf'), '模型二', 'qwen')
        picker = TranslationModelPicker()
        self.assertEqual(picker.choice.count(), 5)
        self.assertEqual(picker.choice.currentData(), 'custom:' + two.id)
        picker.choice.setCurrentIndex(picker.choice.findData('custom:' + one.id))
        self.assertEqual(t.selected_local_model().id, one.id)
        dialog = LocalModelDialog(picker, one.path, one)
        dialog.name.setText('修改名称')
        dialog.execution.setCurrentIndex(dialog.execution.findData('cpu'))
        dialog.save_model()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        picker.refresh()
        self.assertEqual(picker.choice.currentText(), '修改名称')
        restored = TranslationModelPicker()
        self.assertEqual(restored.choice.currentData(), 'custom:' + one.id)
        t.begin_subtitle_session()
        try:
            restored.refresh()
            self.assertFalse(restored.choice.isEnabled())
            self.assertFalse(restored.edit.isEnabled())
        finally:
            t.end_subtitle_session()
        one.path.unlink()
        restored.refresh()
        self.assertIn('文件缺失', restored.choice.currentText())
        self.assertTrue(restored.edit.isEnabled())

    def test_generic_prompt_uses_model_template_and_qwen_disables_thinking(self):
        responses = [io.BytesIO(json.dumps({'choices': [{'message': {'content': '你好'}}]}).encode()),
                     io.BytesIO(json.dumps({'choices': [{'message': {'content': '<think>reason</think>你好'}}]}).encode()),
                     io.BytesIO(json.dumps({'choices': [{'message': {'content': '你好'}}]}).encode())]
        with patch.object(hy_mt, 'ensure_server'), patch.object(hy_mt, 'urlopen', side_effect=responses) as request:
            self.assertEqual(hy_mt.translate('Hello', backend='custom', model=Path('generic.gguf')), '你好')
            generic = json.loads(request.call_args.args[0].data)
            self.assertNotIn('chat_template_kwargs', generic)
            self.assertNotIn('/no_think', generic['messages'][0]['content'])
            self.assertEqual(hy_mt.translate('Hello', backend='custom', model=Path('Qwen.gguf'), profile='qwen'), '你好')
            qwen = json.loads(request.call_args.args[0].data)
            self.assertEqual(qwen['chat_template_kwargs'], {'enable_thinking': False})
            self.assertIn('/no_think', qwen['messages'][0]['content'])
            self.assertEqual(hy_mt.translate('Hello', backend='custom', model=Path('hy.gguf'), profile='hy'), '你好')
            hy = json.loads(request.call_args.args[0].data)
            self.assertTrue(hy['messages'][0]['content'].endswith('\n\nHello'))
            self.assertNotIn('按原文顺序', hy['messages'][0]['content'])

    def test_switching_model_and_execution_replaces_only_owned_server(self):
        first, second = self.model_file('first.gguf'), self.model_file('second.gguf')
        executable = self.root / 'llama-server.exe'
        executable.touch()
        processes = [Mock(), Mock()]
        for process in processes:
            process.poll.return_value = None
        with patch.multiple(hy_mt, SERVER=executable, CACHE=self.root, _process=None, _loaded=None), \
             patch.object(hy_mt, '_ready', side_effect=[False, True, False, True]), \
             patch.object(hy_mt.subprocess, 'Popen', side_effect=processes) as start:
            hy_mt.ensure_server(backend='custom', model=first)
            hy_mt.ensure_server(backend='custom', model=second, execution='cpu')
            processes[0].terminate.assert_called_once()
            automatic, cpu = [call.args[0] for call in start.call_args_list]
            self.assertEqual(automatic[automatic.index('-ngl') + 1], 'auto')
            self.assertIn('--jinja', automatic)
            self.assertIn('--offline', automatic)
            self.assertEqual(cpu[cpu.index('-ngl') + 1], '0')
            self.assertEqual(cpu[cpu.index('--device') + 1], 'none')
            self.assertEqual(hy_mt._loaded[1], str(second.resolve()))


if __name__ == '__main__':
    unittest.main()
