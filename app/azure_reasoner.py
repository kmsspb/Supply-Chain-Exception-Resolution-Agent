from hashlib import sha256
from pathlib import Path

from openai import APIError, APITimeoutError, OpenAI
from pydantic import ValidationError

from app.config import Settings
from app.errors import (
    IncompleteProviderOutput, InvalidProviderOutput, ProviderRefusal,
    ProviderTimeout, ProviderUnavailable, ResolutionError,
)
from app.models import ProviderRecommendation, ReasonerResult, ReasoningContext

PROMPT_VERSION = "resolution_v1"
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")


class AzureOpenAIReasoner:
    provider = "azure_openai"

    def __init__(self, settings: Settings, client=None):
        settings.validate()
        self.settings = settings
        self.client = client if client is not None else OpenAI(
            base_url=settings.base_url.rstrip("/") + "/", api_key=settings.api_key,
            timeout=settings.timeout_seconds, max_retries=0,
        )

    def describe(self) -> dict:
        return {
            "prompt_version": PROMPT_VERSION,
            "prompt_hash": sha256(PROMPT.encode("utf-8")).hexdigest(),
            "deployment": self.settings.deployment,
        }

    def resolve(self, context: ReasoningContext) -> ReasonerResult:
        metadata = self.describe()
        try:
            response = self.client.responses.parse(
                model=self.settings.deployment, instructions=PROMPT,
                input=context.model_dump_json(), text_format=ProviderRecommendation,
                max_output_tokens=self.settings.max_output_tokens, store=False,
            )
            metadata.update({
                "model": response.model, "response_id": response.id,
                "usage": response.usage.model_dump(mode="json") if response.usage else None,
            })
            if any(
                item.type == "message" and any(part.type == "refusal" for part in item.content)
                for item in response.output
            ):
                raise ProviderRefusal()
            if response.status != "completed":
                raise IncompleteProviderOutput()
            if response.output_parsed is None:
                raise InvalidProviderOutput()
            draft = ProviderRecommendation.model_validate(response.output_parsed)
            return ReasonerResult(recommendation=draft, metadata=metadata)
        except APITimeoutError:
            error = ProviderTimeout()
        except APIError:
            error = ProviderUnavailable()
        except (ValidationError, ValueError, TypeError, AttributeError):
            error = InvalidProviderOutput()
        except ResolutionError as exc:
            error = exc
        error.metadata = metadata
        raise error from None
