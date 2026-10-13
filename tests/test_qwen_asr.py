"""Focused checks for local model selection and the speech adapter (no weights)."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from triloa import preferences
from triloa.paths import CACHE, ROOT
from triloa.qwen_asr import (QwenASRSpeechSubtitleRunner, model_ready,
                             parse_transcription, validate_model_folder)
from triloa.resource_setup import ResourceSetupDialog
from triloa.resources import ResourceManager
from triloa.speech import _Utterance
from triloa.subtitles import SubtitleControl

app = QApplication.instance() or QApplication([])
app.setQuitOnLastWindowClosed(False)


def fixture(folder):
    folder.mkdir(parents=True)
    for name in ('config.json', 'preprocessor_config.json', 'tokenizer_config.json', 'vocab.json', 'chat_template.json'):
        (folder / name).write_text(json.dumps({'model_type':'qwen3_asr'}), encoding='utf-8')
    (folder / 'merges.txt').write_text('a b\n', encoding='utf-8')
    header = json.dumps({'test':{'dtype':'F32','shape':[1],'data_offsets':[0,4]}}).encode()
    (folder / 'model.safetensors').write_bytes(len(header).to_bytes(8, 'little') + header + b'\0'*4)
    return folder


class QwenASR(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=CACHE / 'tmp', prefix='qwen-asr-test-')
        self.root = Path(self.temp.name)
        self.folder = fixture(self.root / 'model')
        self.preferences = patch.object(preferences, 'DATA', self.root / 'data')
        self.preferences.start()

    def tearDown(self):
        for widget in app.topLevelWidgets():
            widget.deleteLater()
        app.processEvents()
        self.preferences.stop()
        self.temp.cleanup()

    def test_incomplete_weights_and_text_models_rejected(self):
        self.assertEqual(validate_model_folder(self.folder), self.folder.resolve())
        weights = self.folder / 'model.safetensors'
        weights.write_bytes(weights.read_bytes()[:-1])
        self.assertFalse(model_ready(self.folder))
        (self.folder / 'config.json').write_text('{"model_type":"qwen3"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'GGUF'):
            validate_model_folder(self.folder)

    def test_language_metadata_and_forced_language(self):
        self.assertEqual(parse_transcription('language English<asr_text>Hello.'), ('en', 'Hello.'))
        self.assertEqual(parse_transcription('language Japanese\n<asr_text>こんにちは。'), ('ja', 'こんにちは。'))
        self.assertEqual(parse_transcription('language None<asr_text>'), ('', ''))
        self.assertEqual(parse_transcription('Good morning.', 'en'), ('en', 'Good morning.'))

    def test_qwen_plan_does_not_download_whisper(self):
        plan = ResourceManager().plan(('qwen-asr',))
        self.assertTrue(any(r.feature == 'basic' for r in plan))
        self.assertEqual(len([r for r in plan if r.feature == 'qwen-asr']), 8)
        self.assertFalse(any(r.feature == 'subtitles' for r in plan))
        dialog = ResourceSetupDialog()
        dialog.qwen_asr.setChecked(True)
        dialog.subtitles.setChecked(False)
        self.assertEqual(dialog.features(), ('basic', 'qwen-asr'))
        self.assertFalse(dialog.basic.isEnabled())

    def test_select_folder_persists_path_and_launches_qwen(self):
        control = SubtitleControl(embedded=True)
        with patch('triloa.subtitles.QwenASRSpeechSubtitleRunner') as runner, patch('triloa.subtitles.Thread') as thread, patch('triloa.subtitles.begin_subtitle_session'):
            control.model_selector.setCurrentIndex(control.model_selector.findData('qwen-asr'))
            control._select_qwen_folder(self.folder)
            self.assertEqual(control.model_selector.currentData(), 'qwen-asr')
            self.assertEqual(ROOT / preferences.get('speech.qwen_asr_path'), self.folder.resolve())
            control._start()
            self.assertEqual(runner.call_args.kwargs['model_path'], self.folder.resolve())
            thread.return_value.start.assert_called_once()
            self.assertFalse(control.qwen_folder_button.isEnabled())
            control._stop()
            control._stopped()
        self.assertTrue((self.folder / 'model.safetensors').exists())
        control.close()

    def test_download_sets_directory_and_keeps_selected_recognizer(self):
        preferences.put('speech.model', 'base')
        control = SubtitleControl(embedded=True)
        dialog = ResourceSetupDialog()
        dialog.qwen_asr.setChecked(True)
        dialog.resources_installed.connect(control.refresh_models)
        with patch('triloa.qwen_asr.QWEN_ASR_MODEL_PATH', self.folder), patch.object(dialog, 'refresh_plan', return_value=[]):
            dialog.start_install()
        self.assertEqual(control.model_paths['qwen-asr'], self.folder.resolve())
        self.assertEqual(control.qwen_directory.text(), str(self.folder.resolve()))
        self.assertEqual(control.model_selector.currentData(), 'base')
        self.assertEqual(preferences.get('speech.model'), 'base')
        control.close()

    def test_transformers_adapter_passes_audio_and_returns_text_first(self):
        import numpy as np
        import torch
        processor = Mock()
        processor.apply_chat_template.return_value = 'audio prompt'
        processor.return_value = SimpleNamespace()
        class Inputs(dict):
            def to(self, *args):
                return self
        processor.return_value = Inputs(input_ids=torch.tensor([[1, 2]]))
        processor.batch_decode.return_value = ['language Japanese<asr_text>こんにちは。']
        model = Mock(device='cpu', dtype=torch.float32)
        model.generate.return_value = SimpleNamespace(sequences=torch.tensor([[1, 2, 3]]))
        loaded = SimpleNamespace(model=model, processor=processor)
        runner = QwenASRSpeechSubtitleRunner(model_path=self.folder, language='auto')
        text, language = runner._transcribe(loaded, _Utterance(np.ones((16000, 2), dtype=np.float32), 1, True))
        self.assertEqual((text, language), ('こんにちは。', 'ja'))
        self.assertEqual(processor.call_args.kwargs['audio'][0].shape, (16000,))
        self.assertEqual(processor.call_args.kwargs['sampling_rate'], 16000)
        criteria = model.generate.call_args.kwargs['stopping_criteria'][0]
        runner.stop()
        self.assertTrue(criteria(None, None))

    def test_final_cancels_active_draft(self):
        import numpy as np
        import torch
        class Inputs(dict):
            def to(self, *args):
                return self
        processor = Mock()
        processor.apply_chat_template.return_value = 'audio prompt'
        processor.return_value = Inputs(input_ids=torch.tensor([[1, 2]]))
        model = Mock(device='cpu', dtype=torch.float32)
        runner = QwenASRSpeechSubtitleRunner(model_path=self.folder, mode='live')
        audio = np.ones(16000, dtype=np.float32)
        def finish_phrase(**kwargs):
            runner._enqueue(_Utterance(audio, 1, True))
            self.assertTrue(kwargs['stopping_criteria'][0](None, None))
            return SimpleNamespace(sequences=torch.tensor([[1, 2, 3]]))
        model.generate.side_effect = finish_phrase
        result = runner._transcribe(SimpleNamespace(model=model, processor=processor), _Utterance(audio, 1, False))
        self.assertEqual(result, ('', ''))
        processor.batch_decode.assert_not_called()


if __name__ == '__main__':
    unittest.main()
