from pydantic import BaseModel


class GenericWebhookPayload(BaseModel):
    title: str
    body: str
    url: str | None = None
