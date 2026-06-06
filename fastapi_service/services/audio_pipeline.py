import asyncio
import logging
from services.pion_client import PionClient
from services.gemini_client import GeminiLiveClient
from services.turn_manager import TurnTakingManager

logger = logging.getLogger(__name__)

class AudioPipeline:
    def __init__(self, session_id: str, pion: PionClient, ws):
        self.session_id = session_id
        self.pion = pion
        self.ws = ws
        self.gemini = GeminiLiveClient()
        self.turn_manager = TurnTakingManager(self.gemini)
        self._running = False
        self._tasks = []

    async def run(self):
        self._running = True
        await self.gemini.connect()

        # Run both directions concurrently
        self._tasks = [
            asyncio.create_task(self._user_audio_loop()),
            asyncio.create_task(self._ai_audio_loop()),
        ]
        await asyncio.gather(*self._tasks)

    async def _user_audio_loop(self):
        """Pion → Gemini: stream user audio"""
        logger.info("Starting user audio loop (Pion -> Gemini)")
        try:
            async for pcm_chunk in self.pion.stream_audio_from_pion(self.session_id):
                if not self._running:
                    break

                # Check for interruption (user speaking while AI is talking)
                if self.turn_manager.ai_is_speaking:
                    # Basic RMS check for interruption
                    if self.turn_manager._rms(pcm_chunk) > self.turn_manager.SILENCE_THRESHOLD:
                        await self.turn_manager.handle_interruption()

                await self.gemini.send_audio(pcm_chunk)
                await self.turn_manager.update_voice_activity(pcm_chunk)
        except Exception as e:
            logger.error(f"Error in user audio loop: {e}")

    async def _ai_audio_loop(self):
        """Gemini → Pion: play AI audio back to user"""
        logger.info("Starting AI audio loop (Gemini -> Pion)")
        try:
            while self._running:
                pcm_chunk = await self.gemini.get_response_audio()
                self.turn_manager.ai_is_speaking = True

                # Stream audio chunk to Pion
                async def single_chunk_gen():
                    yield pcm_chunk

                await self.pion.stream_audio_to_pion(self.session_id, single_chunk_gen())
                
                # Check if there's more audio in the queue immediately
                # This is a bit simplified; real logic would handle buffering/pacing
                if self.gemini._response_queue.empty():
                    self.turn_manager.ai_is_speaking = False
        except Exception as e:
            logger.error(f"Error in AI audio loop: {e}")

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        await self.gemini.close()
        logger.info("Audio pipeline stopped")
