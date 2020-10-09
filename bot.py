import asyncio
import logging
from datetime import datetime

import aiohttp.client_exceptions
import aiosqlite
import discord
from discord.ext import commands


class BlackListContext(commands.Context):
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


class BlackListBot(commands.Bot):

    def __init__(self, *args, **kwargs):
        super(BlackListBot, self).__init__(*args, **kwargs)
        self.config = {}
        self.messages = 0
        self.commands_executed = 0
        self.start_time = datetime.now()
        self.cog_groups = {}
        self.db = Database()

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
        # TODO add database file

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


class Database:
    def __init__(self):
        self.db = aiosqlite.connect("database.db")
