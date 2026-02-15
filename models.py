from typing import Optional

from pydantic import BaseModel


class GenericWebhookPayload(BaseModel):
    title: str
    body: str
    url: Optional[str] = None
