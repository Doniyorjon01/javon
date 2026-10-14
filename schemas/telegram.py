"""
Store bot schemas
=================
BotConnectIn  the token from @BotFather. It is write-only: no response ever
              contains it.
BotOut        what the owner's settings page shows, with the two links the owner
              needs: open the bot, and add it to the staff group (that link
              carries a signed code, so only this store can claim the group).
"""

from pydantic import BaseModel, ConfigDict, Field

from models.telegram import BotStatus


class BotConnectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=100)


class BotOut(BaseModel):
    username: str
    status: BotStatus
    last_error: str | None
    bot_url: str  # https://t.me/<username>
    group_linked: bool
    group_title: str | None
    group_link_url: str  # https://t.me/<username>?startgroup=<code>
    mini_app_url: str
