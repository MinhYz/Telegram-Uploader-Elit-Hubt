import edge_tts
from pathlib import Path
from config.settings import DOWNLOAD_DIR
from utils.logger import logger

class VoiceProcessor:
    """Voice Command Processing & Voice Response Synthesizer (Edge-TTS)."""

    @staticmethod
    async def text_to_speech_ogg(text: str, output_path: Path = None) -> Path:
        """Convert text response into Telegram voice OGG audio using Edge-TTS."""
        if not output_path:
            output_path = DOWNLOAD_DIR / "voice_reply.ogg"

        # Limit text length for audio generation
        audio_text = text[:500]
        voice = "vi-VN-HoaiMyNeural" # Natural Vietnamese Neural Voice

        try:
            communicate = edge_tts.Communicate(audio_text, voice)
            await communicate.save(str(output_path))
            logger.info(f"Synthesized Edge-TTS voice reply at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to synthesize voice reply: {e}")
            return output_path

voice_processor = VoiceProcessor()
