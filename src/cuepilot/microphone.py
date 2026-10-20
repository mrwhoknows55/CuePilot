"""Continuous microphone capture with a small PCM chunk boundary."""

from collections.abc import Callable

import sounddevice as sd


class Microphone:
    """Capture 20 ms mono int16 chunks; the optional handler must return promptly."""

    def __init__(self, on_chunk: Callable[[bytes, int], None] | None = None) -> None:
        self.on_chunk = on_chunk
        self.stream: sd.RawInputStream | None = None
        self.device_name = ""
        self.sample_rate = 0
        self.frames_received = 0
        self.peak = 0.0
        self.has_signal = False
        self.error: str | None = None

    @property
    def active(self) -> bool:
        return self.stream is not None and self.stream.active

    def start(self) -> None:
        if self.active:
            return
        if self.stream is not None:
            self.stop()

        device = sd.query_devices(kind="input")
        sample_rate = int(device["default_samplerate"])
        stream = sd.RawInputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=max(1, round(sample_rate * 0.02)),
            callback=self._capture,
        )
        self.device_name = str(device["name"])
        self.sample_rate = sample_rate
        self.frames_received = 0
        self.peak = 0.0
        self.has_signal = False
        self.error = None
        try:
            stream.start()
        except Exception:
            stream.close()
            raise

        self.stream = stream

    def stop(self) -> None:
        stream = self.stream
        self.stream = None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    def take_peak(self) -> float:
        peak = self.peak
        self.peak = 0.0
        return peak

    def _capture(self, data, frames, _time, status) -> None:
        if status:
            self.error = str(status)
        chunk = bytes(data)
        samples = memoryview(chunk).cast("h")
        peak = max(abs(sample) for sample in samples) / 32768
        self.peak = max(self.peak, peak)
        self.has_signal |= peak > 0
        self.frames_received += frames
        if self.on_chunk is not None:
            try:
                self.on_chunk(chunk, self.sample_rate)
            except Exception as exc:
                self.error = f"Audio chunk handler failed: {exc}"
                raise sd.CallbackAbort from exc
