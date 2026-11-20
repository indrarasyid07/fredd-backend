from typing import Literal

from pydantic import BaseModel


class BotOut(BaseModel):
    """One of the platform's shared bots (B-048), as shown to admins on Kanal and Bagikan kode."""

    type: Literal["telegram", "whatsapp"]
    name: str
    # "@FluctuzBot" or "+62 811-0000-0000"; null when the bot is not set up in this environment.
    handle: str | None
    # Chat link without a join code: t.me/<bot> or wa.me/<number>.
    url: str | None
    available: bool
