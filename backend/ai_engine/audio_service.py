import logging
import os
import httpx
import base64
import time
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

class AudioService:
    def __init__(self):
        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        self.deepgram_key = os.getenv("DEEPGRAM_API_KEY")
        # Default ElevenLabs Voice ID (Josh - deep, professional)
        self.voice_id = "pNInz6obpgDQGcFmaJgB" 

    def text_to_speech(self, text):
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
        response = httpx.post(url, json=data, headers=headers, timeout=30)
        latency = time.perf_counter() - start_time
        if response.status_code == 200:
            log.info("ElevenLabs TTS took %.3fs", latency)
            return base64.b64encode(response.content).decode('utf-8')
        log.error("ElevenLabs TTS failed (%s) in %.3fs", response.status_code, latency)
        return None

    def transcribe_audio(self, audio_data_b64, mime_type='audio/webm'):
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
        response = httpx.post(url, content=audio_data, headers=headers, timeout=30)
        latency = time.perf_counter() - start_time
        if response.status_code == 200:
            log.info("Deepgram STT took %.3fs", latency)
            return response.json()['results']['channels'][0]['alternatives'][0]['transcript']
        log.error("Deepgram STT failed (%s) in %.3fs: %s", response.status_code, latency, response.text)
        return None
