import os
import aiohttp
import base64
from dotenv import load_dotenv

load_dotenv()

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

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data, headers=headers) as response:
                if response.status == 200:
                    audio_data = await response.read()
                    return base64.b64encode(audio_data).decode('utf-8')
                else:
                    print(f"ElevenLabs Error: {response.status}")
                    return None

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

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=audio_data, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['results']['channels'][0]['alternatives'][0]['transcript']
                else:
                    error_body = await response.text()
                    print(f"Deepgram Error: {response.status} - {error_body}")
                    return None
