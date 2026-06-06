import asyncio
import base64
import logging
from google import genai
from google.genai.types import LiveConnectConfig, Modality
from core.config import settings

logger = logging.getLogger(__name__)

class GeminiLiveClient:
    def __init__(self):
        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options={"api_version": "v1beta"}
        )
        self.session = None
        self._response_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def connect(self, system_prompt: str = "You are a helpful AI assistant on a video call."):
        logger.info(f"Connecting to Gemini Live API with model {settings.GEMINI_MODEL}")
        try:
            self.session = await self.client.aio.live.connect(
                model=settings.GEMINI_MODEL,
                config=LiveConnectConfig(
                    response_modalities=[Modality.AUDIO],
                    system_instruction=system_prompt,
                )
            )
            self._running = True
            asyncio.create_task(self._receive_loop())
            logger.info("Connected to Gemini Live API")
        except Exception as e:
            logger.error(f"Failed to connect to Gemini: {e}")
            raise

    async def _receive_loop(self):
        """Continuously receive from Gemini and queue responses"""
        try:
            async for message in self.session.receive():
                if not self._running:
                    break
                if message.data:  # Audio response
                    await self._response_queue.put(message.data)
                elif message.server_content:
                    # Handle text or turn completion if needed
                    pass
        except Exception as e:
            logger.error(f"Error in Gemini receive loop: {e}")
        finally:
            self._running = False

    async def send_audio(self, pcm_16khz: bytes):
        """Send user audio to Gemini"""
        if not self.session or not self._running:
            return
        
        try:
            # The SDK might expect base64 or raw bytes depending on the version
            # For google-genai 0.3.0, let's follow the architecture doc's lead
            await self.session.send(
                input={"audio": base64.b64encode(pcm_16khz).decode()},
                end_of_turn=False
            )
        except Exception as e:
            logger.error(f"Error sending audio to Gemini: {e}")

    async def signal_user_done_speaking(self):
        """Tell Gemini user has finished their turn"""
        if self.session and self._running:
            await self.session.send(input={"text": ""}, end_of_turn=True)

    async def interrupt(self):
        """User interrupts Gemini mid-response"""
        if self.session and self._running:
            # Sending a stop signal or empty text with end_of_turn can work
            await self.session.send(input={"text": "[stop]"}, end_of_turn=True)

    async def get_response_audio(self) -> bytes:
        """Get next audio chunk from Gemini (blocks until available)"""
        return await self._response_queue.get()

    async def close(self):
        self._running = False
        if self.session:
            await self.session.close()
            logger.info("Gemini session closed")
