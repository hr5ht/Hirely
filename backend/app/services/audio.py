import asyncio
import base64
import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv
from websockets.asyncio.client import connect

log = logging.getLogger(__name__)

load_dotenv()

# One client for the whole app: reused connections skip a TLS handshake on every call
_http = httpx.AsyncClient(timeout=30)


class LiveTranscription:
    """Deepgram live speech-to-text: audio is fed in while the candidate speaks, so the transcript is
    nearly done when they stop. Chunks that arrive before the connection opens are queued, not lost."""
    URL = "wss://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"  # containerized audio (webm/ogg/mp4): no encoding needed

    def __init__(self, key):
        self.queue = asyncio.Queue()
        self.parts = []
        self.task = asyncio.create_task(self._run(key))

    def feed(self, chunk):
        self.queue.put_nowait(chunk)

    async def _run(self, key):
        async with connect(self.URL, additional_headers={"Authorization": f"Token {key}"}, open_timeout=10) as ws:
            reader = asyncio.create_task(self._read(ws))
            while (chunk := await self.queue.get()) is not None:
                await ws.send(chunk)
            await ws.send(json.dumps({"type": "CloseStream"}))  # Deepgram flushes the last words, then closes
            await asyncio.wait_for(reader, 15)

    async def _read(self, ws):
        async for raw in ws:
            msg = json.loads(raw) if isinstance(raw, str) else {}
            if msg.get("type") == "Results" and msg.get("is_final"):
                if (text := msg["channel"]["alternatives"][0]["transcript"]):
                    self.parts.append(text)

    async def finish(self):
        """The full transcript once the stream is closed, or None if Deepgram failed."""
        self.queue.put_nowait(None)
        start_time = time.perf_counter()
        try:
            await self.task
        except Exception:
            log.exception("Deepgram live STT failed")
            return None
        log.info("Deepgram live STT finished %.3fs after the last chunk", time.perf_counter() - start_time)
        return " ".join(self.parts)

    def cancel(self):
        self.task.cancel()


class AudioService:
    def __init__(self):
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        # Default ElevenLabs Voice ID (Josh - deep, professional)
        self.voice_id = "pNInz6obpgDQGcFmaJgB"

    async def text_to_speech(self, text):
        """Converts text to speech using ElevenLabs and returns base64 audio."""
        if not self.elevenlabs_key or "your_" in self.elevenlabs_key:
            return None

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.elevenlabs_key
        }
        data = {
            "text": text,
            "model_id": "eleven_flash_v2",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        start_time = time.perf_counter()
        response = await _http.post(url, json=data, headers=headers)
        latency = time.perf_counter() - start_time
        if response.status_code == 200:
            log.info("ElevenLabs TTS took %.3fs", latency)
            return base64.b64encode(response.content).decode('utf-8')
        log.error("ElevenLabs TTS failed (%s) in %.3fs", response.status_code, latency)
        return None

    def live_transcription(self):
        """A LiveTranscription to feed audio chunks into, or None without a Deepgram key."""
        if not self.deepgram_key or "your_" in self.deepgram_key:
            return None
        return LiveTranscription(self.deepgram_key)

    async def transcribe_audio(self, audio_data_b64, mime_type='audio/webm'):
        """Transcribes audio using Deepgram of base64 data."""
        if not self.deepgram_key or "your_" in self.deepgram_key:
            return None

        audio_data = base64.b64decode(audio_data_b64)
        url = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"

        # Map browser MIME types to simpler content types for Deepgram
        content_type = mime_type.split(';')[0] if mime_type else 'audio/webm'

        headers = {
            "Authorization": f"Token {self.deepgram_key}",
            "Content-Type": content_type
        }

        start_time = time.perf_counter()
        response = await _http.post(url, content=audio_data, headers=headers)
        latency = time.perf_counter() - start_time
        if response.status_code == 200:
            log.info("Deepgram STT took %.3fs", latency)
            return response.json()['results']['channels'][0]['alternatives'][0]['transcript']
        log.error("Deepgram STT failed (%s) in %.3fs: %s", response.status_code, latency, response.text)
        return None
