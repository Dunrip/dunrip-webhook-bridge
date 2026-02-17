from pydantic import BaseModel, ConfigDict, Field


class GenericWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=4000)
    url: str | None = None
