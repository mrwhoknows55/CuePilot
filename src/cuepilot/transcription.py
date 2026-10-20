"""Turn microphone PCM chunks into local Whisper transcripts."""

import logging
from collections import deque
from math import gcd
from queue import Empty, Full, Queue
from threading import Event, Thread

import numpy as np
from scipy.signal import resample_poly

logger = logging.getLogger(__name__)

MODEL = "mlx-community/whisper-tiny"
TARGET_RATE = 16_000
SPEECH_LEVEL = 0.01
END_SILENCE_SECONDS = 0.5
MIN_SPEECH_SECONDS = 0.2
MAX_SEGMENT_SECONDS = 10


def _disable_tqdm_multiprocessing_lock() -> None:
    """Keep tqdm from creating an unnecessary multiprocessing semaphore."""
    try:
        import tqdm.std

        tqdm.std.TqdmDefaultWriteLock.mp_lock = None
        tqdm.std.TqdmDefaultWriteLock.create_mp_lock = classmethod(
            lambda cls: setattr(cls, "mp_lock", None)
        )
        if hasattr(tqdm.std.tqdm, "_lock"):
            delattr(tqdm.std.tqdm, "_lock")
    except Exception as exc:
        logger.debug("Could not disable tqdm multiprocessing lock: %s", exc)


def _cleanup_tqdm_resources() -> None:
    """Drop tqdm's cached lock after all worker threads have stopped."""
    try:
        import gc

        import tqdm.std

        tqdm.std.TqdmDefaultWriteLock.mp_lock = None
        if hasattr(tqdm.std.tqdm, "_lock"):
            delattr(tqdm.std.tqdm, "_lock")
        gc.collect()
    except Exception as exc:
        logger.debug("Could not clean up tqdm resources: %s", exc)


class SpeechTranscriber:
    """Keep audio capture, speech grouping, and inference on separate threads."""

    def __init__(self) -> None:
        self._chunks: Queue[tuple[bytes, int, int]] = Queue(maxsize=500)
        self._segments: Queue[tuple[bytes, int, int]] = Queue(maxsize=2)
        self._messages: Queue[tuple[int | None, str, str]] = Queue()
        self._stop = Event()
        self._generation = 0
        self.language = "en"
        self.supported_languages: frozenset[str] = frozenset()
        self.dropped_audio = False
        self._segment_thread = Thread(target=self._group_speech, daemon=True)
        self._model_thread = Thread(target=self._transcribe, daemon=True)
        self._closed = False

    def start(self) -> None:
        self._segment_thread.start()
        self._model_thread.start()

    def feed(self, chunk: bytes, sample_rate: int) -> None:
        """Called from the audio callback; never wait for inference here."""
        try:
            self._chunks.put_nowait((chunk, sample_rate, self._generation))
        except Full:
            self.dropped_audio = True

    def reset(self) -> None:
        """Discard pending speech and results when the microphone is paused."""
        self._generation += 1
        self.dropped_audio = False

    def set_language(self, language: str) -> None:
        if language not in self.supported_languages:
            raise ValueError(f"Whisper does not support {language}")
        self.language = language
        self.reset()

    def poll(self) -> list[tuple[str, str]]:
        messages = []
        while True:
            try:
                generation, kind, value = self._messages.get_nowait()
            except Empty:
                return messages
            if generation is None or generation == self._generation:
                messages.append((kind, value))

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._stop.set()
        # Wait for worker threads to finish so their resources are released
        # before the interpreter shuts down.
        threads_stopped = True
        for thread in (self._segment_thread, self._model_thread):
            if thread.is_alive():
                thread.join(timeout=5)
            threads_stopped &= not thread.is_alive()
        if threads_stopped:
            _cleanup_tqdm_resources()
        else:
            logger.warning("Transcription worker did not stop before shutdown")

    def _group_speech(self) -> None:
        preroll: deque[bytes] = deque(maxlen=15)
        segment: list[bytes] = []
        segment_frames = voiced_frames = silent_frames = 0
        current_generation = self._generation

        while not self._stop.is_set():
            try:
                chunk, rate, generation = self._chunks.get(timeout=0.1)
            except Empty:
                continue
            if generation != self._generation:
                continue
            if generation != current_generation:
                preroll.clear()
                segment = []
                segment_frames = voiced_frames = silent_frames = 0
                current_generation = generation

            samples = np.frombuffer(chunk, dtype="<i2")
            if samples.size == 0:
                continue
            waveform = samples.astype(np.float32) / 32768
            level = float(np.sqrt(np.mean(waveform * waveform)))
            speaking = level >= SPEECH_LEVEL

            if not segment:
                if not speaking:
                    preroll.append(chunk)
                    continue
                segment = list(preroll)
                segment_frames = sum(len(part) // 2 for part in segment)
                preroll.clear()

            segment.append(chunk)
            segment_frames += samples.size
            if speaking:
                voiced_frames += samples.size
                silent_frames = 0
            else:
                silent_frames += samples.size

            if (
                silent_frames >= END_SILENCE_SECONDS * rate
                or segment_frames >= MAX_SEGMENT_SECONDS * rate
            ):
                if voiced_frames >= MIN_SPEECH_SECONDS * rate:
                    try:
                        self._segments.put_nowait((b"".join(segment), rate, generation))
                    except Full:
                        self._messages.put((generation, "error", "Transcription is falling behind"))
                segment = []
                segment_frames = voiced_frames = silent_frames = 0

    def _transcribe(self) -> None:
        try:
            # mlx_whisper drives tqdm, which otherwise creates a multiprocessing
            # RLock and leaves a named semaphore behind at shutdown.
            _disable_tqdm_multiprocessing_lock()
            import mlx_whisper
            from mlx_whisper.tokenizer import LANGUAGES

            # This loads (and on first use downloads) the model before the first command.
            mlx_whisper.transcribe(
                np.zeros(TARGET_RATE, dtype=np.float32),
                path_or_hf_repo=MODEL,
                verbose=None,
                language="en",
            )
            self.supported_languages = frozenset(LANGUAGES)
        except Exception as exc:
            logger.exception("Could not load Whisper model")
            self._messages.put((None, "error", f"Model unavailable: {exc}"))
            return
        # Model lifecycle events must survive microphone pauses and language changes.
        self._messages.put((None, "ready", MODEL))

        while not self._stop.is_set():
            try:
                pcm, rate, generation = self._segments.get(timeout=0.1)
            except Empty:
                continue
            if generation != self._generation:
                continue
            try:
                audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
                if rate != TARGET_RATE:
                    factor = gcd(rate, TARGET_RATE)
                    audio = resample_poly(audio, TARGET_RATE // factor, rate // factor)
                result = mlx_whisper.transcribe(
                    audio,
                    path_or_hf_repo=MODEL,
                    verbose=None,
                    condition_on_previous_text=False,
                    language=self.language,
                )
                transcript = result["text"].strip()
            except Exception as exc:
                logger.exception("Whisper transcription failed")
                self._messages.put((generation, "error", f"Transcription failed: {exc}"))
                continue
            if transcript:
                self._messages.put((generation, "transcript", transcript))
