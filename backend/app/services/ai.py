from typing import AsyncGenerator, List, Dict, Union

from app.ai.ollama import OllamaClient
from app.models.message import Message
from app.config import settings

SYSTEM_PROMPT = """You are ALAI, a helpful AI assistant. You are friendly, knowledgeable, and concise.
You can help with a variety of tasks including answering questions, writing code, explaining concepts, and more.
When writing code, use markdown code blocks with appropriate language tags.
If images are provided, analyze and describe them as part of your response.
Be direct and helpful in your responses.

IMPORTANT: Always respond in the same language as the user. If the user writes in Indonesian, respond in Indonesian. If the user writes in English, respond in English. Match the user's language exactly."""


class AIService:
    def __init__(self):
        self.client = OllamaClient()

    def _messages_to_dict(self, messages: list[Message]) -> list[dict]:
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    async def generate_response(
        self, messages: Union[List[Message], List[Dict[str, str]]], user_message: str = None, image_paths: list[str] | None = None, use_agent_model: bool = False
    ) -> str:
        """
        Generate a response from the AI.

        Args:
            messages: Either a list of Message objects, or a list of dicts with 'role' and 'content'
            user_message: Optional user message to append (only if messages are Message objects)
            image_paths: Optional list of image paths to include
            use_agent_model: If True, use the agent model (qwen2.5:14b) for complex reasoning
        """
        # Check if messages are dicts or Message objects
        if messages and isinstance(messages[0], dict):
            # Already dict format - for agent loop
            history = messages
            system_prompt = None  # System prompt should be in messages
        else:
            # Message objects - original behavior
            history = self._messages_to_dict(messages)
            if user_message:
                history.append({"role": "user", "content": user_message})
            system_prompt = SYSTEM_PROMPT

        # Use agent model for complex reasoning tasks
        model_override = settings.OLLAMA_AGENT_MODEL if use_agent_model else None

        return await self.client.chat(history, system_prompt=system_prompt, images=image_paths, model_override=model_override)

    async def generate_response_stream(
        self, messages: Union[List[Message], List[Dict[str, str]]], user_message: str = None, image_paths: list[str] | None = None, use_agent_model: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response from the AI.

        Args:
            messages: Either a list of Message objects, or a list of dicts
            user_message: Optional user message to append
            image_paths: Optional list of image paths to include
        """
        # Check if messages are dicts or Message objects
        if messages and isinstance(messages[0], dict):
            history = messages
            system_prompt = None
        else:
            history = self._messages_to_dict(messages)
            if user_message:
                history.append({"role": "user", "content": user_message})
            system_prompt = SYSTEM_PROMPT

        model_override = settings.OLLAMA_AGENT_MODEL if use_agent_model else None
        async for chunk in self.client.chat_stream(history, system_prompt=system_prompt, images=image_paths, model_override=model_override):
            yield chunk

    async def generate_title(self, first_message: str) -> str:
        prompt = f"""Generate a very short title (max 5 words) for a conversation that starts with this message:
"{first_message}"

Return only the title, nothing else. No quotes, no punctuation at the end.
IMPORTANT: Generate the title in the same language as the message."""

        messages = [{"role": "user", "content": prompt}]
        title = await self.client.chat(messages)
        return title.strip().strip('"').strip("'")[:50]

    async def check_health(self) -> bool:
        return await self.client.check_health()
