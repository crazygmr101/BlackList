import logging
from datetime import datetime, timedelta
from typing import Tuple, Dict, List

import discord
import humanize
from discord.ext import commands

from bot import BlackListContext, BlackListBot, Report


class Safety(commands.Cog):
    def __init__(self, bot: BlackListBot):
        self.bot = bot
        self.cache: Dict[int, Tuple[datetime, bool]] = {}
        logging.info("Loaded Safety")
        self.guild_settings: Dict[int, List[int, int, int]] = {}
        bot.loop.create_task(self._init())

    async def _init(self):
        await self.bot.wait_until_ready()
        rows = await self.bot.db.db.execute_fetchall("select * from guilds")
        for r in rows:
            self.guild_settings[r[0]] = list(r[1:])

    @property
    def description(self):
        return "Safety commands"

    async def lookup_is_banned(self, user: discord.Member) -> Tuple[timedelta, bool]:
        if user in self.cache:
            if (datetime.now() - self.cache[user.id][0]).seconds > 600:
                del self.cache[user.id]
            else:
                return datetime.now() - self.cache[user.id][0], self.cache[user.id][1]
        ban = await self.bot.ksoft.bans.check(user.id)
        self.cache[user.id] = datetime.now(), ban
        return timedelta(0), ban

    @commands.command(
        brief="Looks up a user's information",
        aliases=["userinfo"]
    )
    async def uinfo(self, ctx: BlackListContext, member: discord.Member = None):
        member: discord.Member = member or ctx.author
        ban_updated, is_banned = await self.lookup_is_banned(member)
        reports = await self._get_reports(member)
        await ctx.embed(
            title=f"Lookup for {member}",
            thumbnail=member.avatar_url,
            description=f"{member.mention}'s account was created "
                        f"**{humanize.naturaldelta(datetime.now() - member.created_at)}** ago, on "
                        f"**{humanize.naturaldate(member.created_at)}**. {member.mention} joined the server "
                        f"**{humanize.naturaldelta(datetime.now() - member.joined_at)}**, on "
                        f"**{humanize.naturaldate(member.joined_at)}**. They are **{'not ' if not is_banned else ''}"
                        f"globally banned** on KSoft, last updated **{humanize.naturaldelta(ban_updated)}** ago. "
                        f"They {'do not ' if not reports else ''}have {'any' if not reports else len(reports)} reports."
        )

    @commands.guild_only()
    @commands.command(
        brief="Sets the channel for incoming reports"
    )
    async def incoming(self, ctx: BlackListContext, channel: discord.TextChannel = None):
        await self._ensure_guild_entry(ctx.guild)
        self.guild_settings[ctx.guild_id][0] = channel.id if channel else 0
        await self.bot.db.db.execute("UPDATE guilds SET incoming=? WHERE id=?",
                                     (self.guild_settings[ctx.guild_id][0], ctx.guild_id))
        await self.bot.db.db.commit()
        if channel:
            await ctx.send_info(f"Channel for incoming reports set to {channel.mention}")
        else:
            await ctx.send_info("Channel for incoming reports cleared")

    @commands.guild_only()
    @commands.command(
        brief="Sets the channel for blacklisted reports to show up."
    )
    async def blacklisted(self, ctx: BlackListContext, channel: discord.TextChannel = None):
        await self._ensure_guild_entry(ctx.guild)
        self.guild_settings[ctx.guild_id][1] = channel.id if channel else 0
        await self.bot.db.db.execute("UPDATE guilds SET public=? WHERE id=?",
                                     (self.guild_settings[ctx.guild_id][1], ctx.guild_id))
        await self.bot.db.db.commit()
        if channel:
            await ctx.send_info(f"Channel for blacklisted reports set to {channel.mention}")
        else:
            await ctx.send_info("Channel for blacklisted reports cleared")

    @commands.guild_only()
    @commands.command(
        brief="Sets the channel for new users to show up. This only sends a message if someone has been banned on "
              "KSoft, has an account newer than a week, or has reports here"
    )
    async def newusers(self, ctx: BlackListContext, channel: discord.TextChannel = None):
        await self._ensure_guild_entry(ctx.guild)
        self.guild_settings[ctx.guild_id][2] = channel.id if channel else 0
        await self.bot.db.db.execute("UPDATE guilds SET warn_incoming=? WHERE id=?",
                                     (self.guild_settings[ctx.guild_id][2], ctx.guild_id))
        await self.bot.db.db.commit()
        if channel:
            await ctx.send_info(f"Channel for new user reports set to {channel.mention}")
        else:
            await ctx.send_info("Channel for new user reports cleared")

    @commands.guild_only()
    @commands.command(
        brief="Lists the server's current settings"
    )
    async def settings(self, ctx: BlackListContext):
        if ctx.guild_id not in self.guild_settings:
            self.guild_settings[ctx.guild_id] = [0, 0, 0]
            await self.bot.db.db.execute_insert("INSERT INTO guilds VALUES (?,?,?,?)", (ctx.guild_id, 0, 0, 0))
        await self.bot.db.db.commit()
        rec = self.guild_settings[ctx.guild_id]
        await ctx.embed(
            title=f"{ctx.guild}",
            description=f"New users channel: {self.bot.get_channel(rec[2])}\n"
                        f"Incoming report channel: {self.bot.get_channel(rec[0])}\n"
                        f"Blacklisted channel: {self.bot.get_channel(rec[1])}"
        )

    async def _get_reports(self, user: discord.Member):
        rows = await self.bot.db.db.execute_fetchall("SELECT * FROM reports WHERE reported=?", (user.id,))
        return [Report(*r) for r in rows]

    async def _ensure_guild_entry(self, guild: discord.Guild):
        if guild.id not in self.guild_settings:
            self.guild_settings[guild.id] = [0, 0, 0]
            await self.bot.db.db.execute_insert("INSERT INTO guilds VALUES (?,?,?,?)", (guild.id, 0, 0, 0))
        await self.bot.db.db.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self._ensure_guild_entry(member.guild)
        account_age = (datetime.now() - member.created_at).days
        reports = await self._get_reports(member)
        updated, banned = self.lookup_is_banned(member)

        if (account_age < 7 or reports or banned) and self.bot.get_channel(self.guild_settings[member.guild.id][2]) \
                and not member.bot:
            await self.bot.get_channel(self.guild_settings[member.guild.id][2]).send(
                embed=discord.Embed(
                    title="Suspicious Account Joined",
                    colour=discord.Colour.red(),
                    description=
                    f"{member.mention}'s account was created "
                    f"**{humanize.naturaldelta(datetime.now() - member.created_at)}** ago, on "
                    f"**{humanize.naturaldate(member.created_at)}**. {member.mention} joined the server "
                    f"**{humanize.naturaldelta(datetime.now() - member.joined_at)}**, on "
                    f"**{humanize.naturaldate(member.joined_at)}**. They are **{'not ' if not banned else ''}"
                    f"globally banned** on KSoft, last updated **{humanize.naturaldelta(updated)}** ago. "
                    f"They {'do not ' if not reports else ''}have {'any' if not reports else len(reports)} reports."
                )
            )


def setup(bot):
    bot.add_cog(Safety(bot))
