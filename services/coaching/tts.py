from io import BytesIO
from gtts import gTTS

class TextToSpeech:
    REQUEST_TIMEOUT = 8

    def speak(self, text, lang="en"):
        cleaned = (text or "").strip()

        if not cleaned:
            return None
        
        buffer = BytesIO()
        gTTS(
            text=cleaned,
            lang=lang,
            timeout=self.REQUEST_TIMEOUT,
        ).write_to_fp(buffer)
        buffer.seek(0)
    
        return buffer.read()
