import asyncio
import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union, List, Tuple
import string
import random
import aiohttp.client_exceptions
import aiosqlite
import discord
import ksoftapi
from aiosqlite import Connection

from discord.ext import commands

SQL_STRING = """
CREATE TABLE IF NOT EXISTS "guilds" (
    "id" INTEGER NOT NULL,
    "incoming" INTEGER DEFAULT 0,
    "public" INTEGER DEFAULT 0,
    "warn_incoming" INTEGER DEFAULT 0
);;
CREATE TABLE IF NOT EXISTS "reports" (
    "id" TEXT NOT NULL,
    "reporter" INTEGER NOT NULL,
    "guild" INTEGER NOT NULL,
    "reported" INTEGER NOT NULL,
    "reason" TEXT NOT NULL
);;
CREATE TABLE IF NOT EXISTS "messages" (
    "guild" INTEGER NOT NULL,
    "message" INTEGER NOT NULL,
    "report" TEXT NOT NULL,
    FOREIGN KEY(report) REFERENCES reports(id),
    FOREIGN KEY(guild) REFERENCES guilds(id)
);;
CREATE TABLE IF NOT EXISTS "banned" (
    "id" INTEGER NOT NULL,
    "is_user" INTEGER NOT NULL
)
"""


class BlackListContext(commands.Context):
    INFO = 0
    ERROR = 1
    OK = 2

    def __init__(self, **kwargs):
        super(BlackListContext, self).__init__(**kwargs)

    @property
    def guild_id(self) -> int:
        return self.guild.id

    @property
    def channel_id(self) -> int:
        return self.channel.id

    @property
    def author_id(self) -> int:
        return self.author.id

    async def send_info(self, message: str):
        await self._respond(message, discord.Color.blue())

    async def send_ok(self, message: str):
        await self._respond(message, discord.Color.green())

    async def send_error(self, message: str):
        await self._respond(message, discord.Color.red())

    async def _respond(self, message: str, color: discord.Color):
        await self.send(embed=discord.Embed(
            description=f"{self.author} {message}",
            color=color
        ))

    async def get_color(self, typ: int):
        return [discord.Colour.blue(), discord.Colour.red(), discord.Colour.green()][typ]

    # noinspection PyDefaultArgument
    async def embed(self, *,
                    author: str = None,
                    description: str = None,
                    title: str = None,
                    title_url: str = None,
                    typ: int = INFO,
                    fields: List[Tuple[str, str]] = None,
                    thumbnail: str = None,
                    clr: discord.Colour = None,
                    image: Union[str, io.BufferedIOBase] = None,
                    footer: str = None,
                    not_inline: List[int] = [],
                    trash_reaction: bool = False):
        if typ and clr:
            raise ValueError("typ and clr can not be both defined")
        embed = discord.Embed(
            title=title,
            description=description,
            colour=(await self.get_color(typ) if not clr else clr),
            title_url=title_url
        )
        if author:
            embed.set_author(name=author)
        if image:
            if isinstance(image, str):
                embed.set_image(url=image)
                f = None
            else:
                image.seek(0)
                f = discord.File(image, filename="image.png")
                embed.set_image(url="attachment://image.png")
        else:
            f = None
        if footer:
            embed.set_footer(text=footer)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        for n, r in enumerate(fields or []):
            embed.add_field(name=r[0], value=r[1] or "None", inline=n not in not_inline)
        msg = await self.send(embed=embed, file=f)
        if trash_reaction:
            await self.trash_reaction(msg)

    async def trash_reaction(self, message: discord.Message):
        if len(message.embeds) == 0:
            return

        def check(_reaction: discord.Reaction, _user: Union[discord.User, discord.Member]):
            return all([
                _user.id == self.author.id or _user.guild_permissions.manage_messages,
                _reaction.message.id == message.id,
                str(_reaction) == "🗑️"
            ])

        await message.add_reaction("🗑️")
        await asyncio.sleep(0.5)
        try:
            _, _ = await self.bot.wait_for("reaction_add", timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await message.clear_reactions()
        else:
            await message.delete()


class BlackListBot(commands.Bot):

    def __init__(self, *args, **kwargs):
        super(BlackListBot, self).__init__(*args, **kwargs)
        self.config = {}
        self.messages = 0
        self.commands_executed = 0
        self.start_time = datetime.now()
        self.cog_groups = {}
        self.db = Database()
        self.ksoft: Optional[ksoftapi.Client] = None

        #  self.version = "+".join(subprocess.check_output(["git", "describe", "--tags"]).
        #                        strip().decode("utf-8").split("-")[:-1])

        async def increment_command_count(ctx):
            self.commands_executed += 1

        self.add_listener(
            increment_command_count,
            "on_command_completion"
        )

    async def on_message(self, message: discord.Message):
        ctx: BlackListContext = await self.get_context(message, cls=BlackListContext)
        await self.invoke(ctx)

    async def start(self, *args, **kwargs):  # noqa: C901
        """|coro|
        A shorthand coroutine for :meth:`login` + :meth:`connect`.
        Raises
        -------
        TypeError
            An unexpected keyword argument was received.
        """
        bot = kwargs.pop('bot', True)
        reconnect = kwargs.pop('reconnect', True)
        await self.db.load()

        logging.info("bot:Loading KSoft Client")
        self.ksoft = ksoftapi.Client(os.getenv("KSOFT"))
        logging.info("bot:Loaded KSoft Client")

        if kwargs:
            raise TypeError("unexpected keyword argument(s) %s" % list(kwargs.keys()))

        for i in range(0, 6):
            try:
                await self.login(*args, bot=bot)
                break
            except aiohttp.client_exceptions.ClientConnectionError as e:
                logging.warning(f"bot:Connection {i}/6 failed")
                logging.warning(f"bot:  {e}")
                logging.warning(f"bot: waiting {2 ** (i + 1)} seconds")
                await asyncio.sleep(2 ** (i + 1))
                logging.info("bot:attempting to reconnect")
        else:
            logging.error("bot: FATAL failed after 6 attempts")
            return

        for cog in self.cogs:
            cog = self.get_cog(cog)
            if not cog.description and cog.qualified_name not in self.cog_groups["Hidden"]:
                logging.error(f"bot:cog {cog} has no description")
                return

        missing_brief = []
        for command in self.commands:
            if not command.brief:
                missing_brief.append(command)

        if missing_brief:
            logging.error("bot:the following commands are missing help text")
            for i in missing_brief:
                logging.error(f"bot: - {i.cog.qualified_name}.{i.name}")
            return

        await self.connect(reconnect=reconnect)

    def set_cog_group(self, cog: str, group: str):
        if group not in self.cog_groups:
            self.cog_groups[group] = [cog]
        else:
            self.cog_groups[group].append(cog)


@dataclass(frozen=True)
class Report:
    id: int
    reporter: int
    guild: int
    reported: int
    reason: str
    images: str


class Database:
    def __init__(self):
        self.db: Optional[Connection] = None
        self.randomness = string.ascii_letters + string.digits

    async def load(self):
        self.db = await aiosqlite.connect("database.db")
        for i in SQL_STRING.split(";;"):
            await self.db.execute(i)
        await self.db.commit()
