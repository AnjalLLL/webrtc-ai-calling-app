import asyncio
import struct
import logging

logger = logging.getLogger(__name__)

class TurnTakingManager:
    SILENCE_THRESHOLD = 500       # RMS amplitude below = silence
    SILENCE_FRAMES_FOR_EOT = 30   # ~600ms of silence = end of turn (assuming 20ms chunks)

    def __init__(self, gemini_client):
        self.gemini = gemini_client
        self.ai_is_speaking = False
        self._silence_counter = 0

    def _rms(self, pcm_bytes: bytes) -> float:
        if not pcm_bytes:
            return 0
        # Assume 16-bit PCM
        samples = struct.unpack(f"{len(pcm_bytes)//2}h", pcm_bytes)
        if not samples:
            return 0
        return (sum(s**2 for s in samples) / len(samples)) ** 0.5

    async def update_voice_activity(self, pcm_chunk: bytes):
        rms = self._rms(pcm_chunk)
        if rms < self.SILENCE_THRESHOLD:
            self._silence_counter += 1
            if self._silence_counter >= self.SILENCE_FRAMES_FOR_EOT:
                await self.gemini.signal_user_done_speaking()
                self._silence_counter = 0
                logger.debug("End of turn detected (silence)")
        else:
            self._silence_counter = 0

    async def handle_interruption(self):
        await self.gemini.interrupt()
        self.ai_is_speaking = False
        logger.info("User interrupted AI")
