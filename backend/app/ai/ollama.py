import json
import base64
import time
from pathlib import Path
from typing import AsyncGenerator
import httpx

from app.config import settings


def log(message: str):
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [OLLAMA] {message}")


class OllamaClient:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.text_model = settings.OLLAMA_TEXT_MODEL
        self.vision_model = settings.OLLAMA_VISION_MODEL

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _format_messages(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        images: list[str] | None = None,
    ) -> list[dict]:
        formatted = []

        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})

        for i, msg in enumerate(messages):
            message = {
                "role": msg["role"],
                "content": msg["content"],
            }

            # Add images to the last user message
            if (
                images
                and i == len(messages) - 1
                and msg["role"] == "user"
            ):
                encoded_images = []
                for img_path in images:
                    path = Path(img_path)
                    log(
                        f"Encoding image: {img_path}"
                        f" (exists: {path.exists()})"
                    )
                    if path.exists():
                        encoded_images.append(
                            self._encode_image(img_path)
                        )
                        size_kb = path.stat().st_size / 1024
                        log(
                            f"✓ Image encoded successfully"
                            f" ({size_kb:.1f} KB)"
                        )
                if encoded_images:
                    message["images"] = encoded_images
                    log(
                        f"✓ Added {len(encoded_images)}"
                        " image(s) to request"
                    )

            formatted.append(message)

        return formatted

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        images: list[str] | None = None,
        model_override: str | None = None,
    ) -> str:
        formatted_messages = self._format_messages(
            messages, system_prompt, images
        )

        # Choose model: override > vision (if images) > text
        if model_override:
            model = model_override
        else:
            model = self.vision_model if images else self.text_model
        log(f"Model: {model} | Images: {len(images) if images else 0}")

        start_time = time.time()
        async with httpx.AsyncClient(timeout=120.0) as client:
            log("Sending non-streaming request...")
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": formatted_messages,
                    "stream": False,
                    "keep_alive": -1,
                    "options": {
                        "num_ctx": 16384,
                        "num_predict": 4096,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            elapsed = time.time() - start_time
            content = data.get("message", {}).get("content", "")
            log(
                f"✓ Response received ({len(content)} chars)"
                f" in {elapsed:.2f}s"
            )
            return content

    async def chat_stream(
        self,
        messages: list[dict],
        system_prompt: str | None = None,
        images: list[str] | None = None,
        model_override: str | None = None,
    ) -> AsyncGenerator[str, None]:
        formatted_messages = self._format_messages(
            messages, system_prompt, images
        )

        # Choose model: override > vision (if images) > text
        if model_override:
            model = model_override
        elif images:
            model = self.vision_model
        else:
            model = self.text_model
        # Larger/override models and vision models need more time
        timeout = 300.0 if (images or model_override) else 120.0

        log("=" * 50)
        log(f"Model: {model}")
        log(f"Images: {len(images) if images else 0}")
        log(f"History messages: {len(messages)}")
        log(f"Timeout: {timeout}s")
        log("=" * 50)

        # Reasoning paragraph starters — paragraphs starting with these
        # are internal reasoning and should be stripped from the output.
        _REASONING_STARTERS = (
            "okay", "ok,", "ok.", "let me", "let's", "let us",
            "i'll", "i will", "i need", "i'm going",
            "first,", "first i", "alright", "sure,", "so,",
            "now,", "well,", "the user", "looking at", "based on",
            "to answer", "in that section", "this section",
            "another section", "also,", "also section",
            "from the retrieved",
        )

        def _is_reasoning_para(para: str) -> bool:
            s = para.strip().lower()
            return any(s.startswith(r) for r in _REASONING_STARTERS)

        def _is_answer_para(para: str) -> bool:
            s = para.strip()
            # Headings, citations, structured list items, or content that
            # clearly comes from the document (not model narration)
            return bool(
                s.startswith("#")
                or s.startswith("[")
                or s.startswith("**")
                or s.startswith("- ")
                or s.startswith("* ")
                or (len(s) > 0 and s[0].isdigit() and ". " in s[:5])
            )

        start_time = time.time()
        token_count = 0

        async with httpx.AsyncClient(timeout=timeout) as client:
            log(f"Connecting to {self.base_url}/api/chat ...")
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": formatted_messages,
                    "stream": True,
                    "keep_alive": -1,
                    "think": False,
                    "options": {
                        "num_ctx": 16384,
                        "num_predict": 4096,
                    },
                },
            ) as response:
                response.raise_for_status()
                first_token_time = None
                log("✓ Connected! Streaming response...")
                in_think = False
                # Paragraph-level preamble filter:
                # accumulate text, discard reasoning paragraphs,
                # yield from the first non-reasoning paragraph onward.
                preamble_buf = ""
                preamble_done = False
                skipped_paras = 0
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if (
                                "message" in data
                                and "content" in data["message"]
                            ):
                                content = data["message"]["content"]
                                if content:
                                    # Strip <think>...</think> blocks
                                    if "<think>" in content:
                                        in_think = True
                                    if in_think:
                                        if "</think>" in content:
                                            in_think = False
                                            content = content.split(
                                                "</think>"
                                            )[-1]
                                        else:
                                            content = ""
                                    # Paragraph-level reasoning filter
                                    if content and not preamble_done:
                                        preamble_buf += content
                                        # Process complete paragraphs
                                        while "\n\n" in preamble_buf:
                                            para, preamble_buf = (
                                                preamble_buf.split(
                                                    "\n\n", 1
                                                )
                                            )
                                            if _is_answer_para(para):
                                                # Found answer — emit and
                                                # switch to pass-through
                                                content = (
                                                    para
                                                    + "\n\n"
                                                    + preamble_buf
                                                )
                                                preamble_buf = ""
                                                preamble_done = True
                                                log(
                                                    f"⚠ Stripped"
                                                    f" {skipped_paras}"
                                                    " reasoning para(s)"
                                                )
                                                break
                                            elif _is_reasoning_para(para):
                                                skipped_paras += 1
                                                log(
                                                    f"  skip para:"
                                                    f" {para[:60]!r}"
                                                )
                                            else:
                                                # Ambiguous — keep it
                                                content = (
                                                    para
                                                    + "\n\n"
                                                    + preamble_buf
                                                )
                                                preamble_buf = ""
                                                preamble_done = True
                                                break
                                        else:
                                            # No complete paragraph yet
                                            # Safety valve: if buffer is
                                            # huge and no answer found,
                                            # flush it to avoid stalling
                                            if len(preamble_buf) > 8000:
                                                log(
                                                    "⚠ Preamble buffer"
                                                    " overflow — flushing"
                                                )
                                                content = preamble_buf
                                                preamble_buf = ""
                                                preamble_done = True
                                            else:
                                                content = ""
                                    if content:
                                        if first_token_time is None:
                                            first_token_time = time.time()
                                            ttft = (
                                                first_token_time
                                                - start_time
                                            )
                                            log(
                                                f"⚡ First token"
                                                f" (TTFT: {ttft:.2f}s)"
                                            )
                                        token_count += 1
                                        yield content
                            if data.get("done", False):
                                # Flush any remaining buffer if stream ends
                                # while still filtering
                                if preamble_buf and not preamble_done:
                                    yield preamble_buf
                                elapsed = time.time() - start_time
                                log(
                                    f"✓ Stream complete:"
                                    f" {token_count} tokens"
                                    f" in {elapsed:.2f}s"
                                )
                                break
                        except json.JSONDecodeError:
                            continue

    async def check_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{self.base_url}/api/tags"
                )
                return response.status_code == 200
        except Exception:
            return False
