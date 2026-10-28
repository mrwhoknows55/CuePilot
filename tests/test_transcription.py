import unittest
from contextlib import nullcontext
from math import ceil
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from cuepilot.transcription import (
    MAX_SEGMENT_SECONDS,
    TARGET_RATE,
    VAD_WINDOW,
    SpeechTranscriber,
)


class SpeechGroupingTests(unittest.TestCase):
    def group(self, probabilities, *, rate=TARGET_RATE, amplitude=10, reset_after=None):
        transcriber = SpeechTranscriber()
        calls = []
        probabilities = list(probabilities)
        # Feed the same 20 ms PCM chunks that the microphone produces.
        frame_count = len(probabilities) * VAD_WINDOW * rate // TARGET_RATE
        pcm = np.full(frame_count, amplitude, dtype='<i2')
        chunks = [part.tobytes() for part in np.array_split(pcm, frame_count // (rate // 50))]
        for chunk in chunks:
            transcriber.feed(chunk, rate)

        def infer(window, sample_rate):
            self.assertEqual(window.shape, (VAD_WINDOW,))
            self.assertEqual(window.dtype, np.float32)
            self.assertEqual(sample_rate, TARGET_RATE)
            calls.append(window.copy())
            if reset_after == len(calls):
                transcriber.reset()
                # Old queued chunks must be discarded, and new audio starts fresh.
                new_pcm = np.full(VAD_WINDOW, amplitude, dtype='<i2').tobytes()
                for _ in probabilities[reset_after:]:
                    transcriber.feed(new_pcm, TARGET_RATE)
            if len(calls) == len(probabilities):
                transcriber._stop.set()
            return SimpleNamespace(item=lambda: probabilities[len(calls) - 1])

        model = Mock(side_effect=infer)
        torch = SimpleNamespace(
            Tensor=type('Tensor', (), {}),
            set_num_threads=Mock(),
            from_numpy=lambda array: array,
            inference_mode=nullcontext,
        )
        with patch.dict('sys.modules', {
            'torch': torch,
            'silero_vad': SimpleNamespace(load_silero_vad=lambda: model),
        }):
            transcriber._group_speech()
        return transcriber, calls, model

    def test_quiet_speech_is_detected_and_waits_for_silence(self):
        transcriber, calls, _ = self.group([0.1] * 2 + [0.9] * 7 + [0.1] * 16)
        audio, generation = transcriber._segments.get_nowait()
        self.assertEqual(generation, 0)
        self.assertEqual(audio.size, 25 * VAD_WINDOW)
        np.testing.assert_array_equal(audio, np.concatenate(calls))
        self.assertTrue(transcriber._segments.empty())
        self.assertIn(('vad_ready', 'Silero VAD'), transcriber.poll())

    def test_loud_noise_is_not_speech(self):
        transcriber, _, _ = self.group([0.1] * 25, amplitude=32767)
        self.assertTrue(transcriber._segments.empty())

    def test_very_short_speech_is_discarded(self):
        transcriber, _, _ = self.group([0.9] * 6 + [0.1] * 16)
        self.assertTrue(transcriber._segments.empty())

    def test_device_audio_is_resampled_before_detection(self):
        for rate in [44_100, 48_000]:
            with self.subTest(rate=rate):
                transcriber, _, _ = self.group([0.1] * 2 + [0.9] * 7 + [0.1] * 16, rate=rate)
                audio, _ = transcriber._segments.get_nowait()
                self.assertEqual(audio.size, 25 * VAD_WINDOW)
                self.assertEqual(audio.dtype, np.float32)

    def test_continuous_speech_is_bounded(self):
        windows = ceil(MAX_SEGMENT_SECONDS * TARGET_RATE / VAD_WINDOW)
        transcriber, _, _ = self.group([0.9] * windows)
        audio, _ = transcriber._segments.get_nowait()
        self.assertEqual(audio.size, windows * VAD_WINDOW)

    def test_pause_discards_partial_speech_and_resets_model(self):
        transcriber, _, model = self.group([0.9] * 9 + [0.1] * 16, reset_after=2)
        audio, generation = transcriber._segments.get_nowait()
        self.assertEqual(generation, 1)
        self.assertEqual(audio.size, 23 * VAD_WINDOW)
        self.assertEqual(model.reset_states.call_count, 2)
        self.assertTrue(transcriber._segments.empty())

    def test_vad_load_failure_is_reported_across_resets(self):
        transcriber = SpeechTranscriber()
        with (
            patch.dict('sys.modules', {
                'torch': SimpleNamespace(set_num_threads=Mock()),
                'silero_vad': SimpleNamespace(load_silero_vad=Mock(side_effect=OSError('bad model'))),
            }),
            self.assertLogs('cuepilot.transcription', level='ERROR'),
        ):
            transcriber._group_speech()
        transcriber.reset()
        self.assertEqual(transcriber.poll(), [('vad_error', 'Silero VAD unavailable: bad model')])


class TranscriptionLatencyTests(unittest.TestCase):
    def test_whisper_timings_preserve_results_and_errors(self):
        for fails in (False, True):
            with self.subTest(fails=fails):
                transcriber = SpeechTranscriber()
                transcriber._segments.put((np.zeros(TARGET_RATE, dtype=np.float32), 0))

                def transcribe(audio, **kwargs):
                    if 'condition_on_previous_text' not in kwargs:
                        return {'text': ''}  # Model warmup.
                    transcriber._stop.set()
                    if fails:
                        raise RuntimeError('inference failed')
                    return {'text': ' mute '}

                with (
                    patch.dict('sys.modules', {
                        'mlx_whisper': SimpleNamespace(transcribe=transcribe),
                        'mlx_whisper.tokenizer': SimpleNamespace(LANGUAGES={'en': 'English'}),
                    }),
                    patch('cuepilot.transcription._disable_tqdm_multiprocessing_lock'),
                    self.assertLogs('cuepilot.transcription', level='INFO') as logs,
                ):
                    transcriber._transcribe()
                self.assertTrue(any(
                    'operation=whisper_load_and_warmup' in line and 'status=ok' in line
                    for line in logs.output
                ))
                status = 'error' if fails else 'ok'
                self.assertTrue(any(
                    'operation=whisper_transcription' in line and f'status={status}' in line
                    for line in logs.output
                ))
                expected = ('error', 'Transcription failed: inference failed') if fails else ('transcript', 'mute')
                self.assertIn(expected, transcriber.poll())


if __name__ == '__main__':
    unittest.main()
