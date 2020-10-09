import logging
import random
import string
from datetime import datetime, timedelta
from typing import Tuple, Dict, List

import discord
import humanize
from discord.ext import commands

from bot import BlackListContext, BlackListBot, Report


def add_desc(msg: discord.Message, text: str) -> discord.Embed:
    embed = msg.embeds[0]
    embed.description += f"\n{text}"
    return embed


class Safety(commands.Cog):
    def __init__(self, bot: BlackListBot):
        self.bot = bot
        self.cache: Dict[int, Tuple[datetime, bool]] = {}
        logging.info("Loaded Safety")
        self.guild_settings: Dict[int, List[int, int, int]] = {}
        self.banned_users: List = []
        self.banned_guilds: List = []
        self.reports: List[Report] = []
        self.messages: List[Tuple[int, int, str]] = []
        bot.loop.create_task(self._init())

    async def _init(self):
        await self.bot.wait_until_ready()
        rows = await self.bot.db.db.execute_fetchall("select * from guilds")
        for r in rows:
            self.guild_settings[r[0]] = list(r[1:])
        rows = await self.bot.db.db.execute_fetchall("select * from banned")
        for r in rows:
            if r[1]:
                self.banned_users.append(r[0])
            else:
                self.banned_guilds.append(r[0])
        rows = await self.bot.db.db.execute_fetchall("select * from messages")
        for r in rows:
            self.messages.append(tuple(r))
        rows = await self.bot.db.db.execute_fetchall("select * from reports")
        for r in rows:
            self.reports.append(Report(*r))

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
              "KSoft, has an account newer than a month, or has reports here"
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
        updated, banned = await self.lookup_is_banned(member)

        if (account_age < 30 or reports or banned) and self.bot.get_channel(self.guild_settings[member.guild.id][2]) \
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

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(
        brief="Starts a report"
    )
    async def report(self, ctx: BlackListContext):
        randomness = string.ascii_letters + string.digits
        report_id = "".join(random.choice(randomness) for _ in range(20))
        if ctx.guild_id in self.banned_guilds:
            return await ctx.send_error("This server is unable to make reports.")
        if ctx.author_id in self.banned_users:
            return await ctx.send_error("You are unable to make reports.")
        await ctx.send("Starting a report. Send the ID of the user you want to report. They must be in this server.")
        member = await ctx.input(int, ch=ctx.guild.get_member)
        if not member:
            return await ctx.send("Cancelled")
        await ctx.send("Send the reason you'd like to report them for. "
                       "1000 character max, you can include image links.")
        reason = await ctx.input(str)
        if not reason:
            return await ctx.send("Cancelled")
        msg = await ctx.embed(
            title="Pending confirmation",
            description=reason[:1000],
            fields=[
                ("User", f"{ctx.guild.get_member(member)} - {member}")
            ]
        )
        if not await ctx.confirm("Submit report?", "Submitting report", "Submission cancelled"):
            return
        await msg.delete()
        for guild, config in self.guild_settings.items():
            channel = self.bot.get_channel(config[0])
            if not channel:
                continue
            self.reports.append(Report(report_id, ctx.author_id, ctx.guild_id, member, reason))
            prev_reports = len(await self._get_reports(ctx.guild.get_member(member)))
            await self.bot.db.db.execute_insert("insert into reports values (?,?,?,?,?)",
                                                (report_id, ctx.author_id, ctx.guild_id, member, reason))
            msg = await ctx.channel_embed(
                channel=channel,
                title="Incoming report",
                description=reason,
                fields=[
                    ("User", f"{ctx.guild.get_member(member)} - {member}"),
                    ("KSoft Banned", (await self.lookup_is_banned(ctx.guild.get_member(member)))[1]),
                    ("Previous Reports", prev_reports),
                    ("Actions", f"{ctx.KICK} Kick - {ctx.IGNORE} Ignore - {ctx.BAN} Ban - {ctx.PUBLIC} Publish")
                ]
            )
            await msg.add_reaction(ctx.KICK)
            await msg.add_reaction(ctx.IGNORE)
            await msg.add_reaction(ctx.BAN)
            await msg.add_reaction(ctx.PUBLIC)
            await self.bot.db.db.execute_insert("insert into messages values (?,?,?)",
                                                (ctx.guild_id, msg.id, report_id))
            self.messages.append((ctx.guild_id, msg.id, report_id))

        await self.bot.db.db.commit()
        await ctx.send_ok("Report was sent!")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member.bot:
            return
        record: Tuple[int, int, str]
        print("e")
        for r in self.messages:
            if payload.message_id == r[1]:
                record = r
                break
        else:
            return
        msg: discord.Message = await self.bot.get_channel(payload.channel_id).fetch_message(payload.message_id)
        if payload.emoji.name not in (BlackListContext.PUBLIC, BlackListContext.BAN,
                                      BlackListContext.KICK, BlackListContext.IGNORE):
            return

        reaction: discord.Reaction = list(filter(lambda x: x.emoji == payload.emoji.name, msg.reactions))[0]

        # get the report for the message
        report: Report
        for r in self.reports:
            if r.id == record[2]:
                report = r
                break
        else:
            return

        guild: discord.Guild = payload.member.guild
        member: discord.Member = payload.member

        if reaction.emoji == BlackListContext.IGNORE:
            if not member.guild_permissions.ban_members:
                await reaction.remove(member)
                return
            await msg.clear_reactions()
            await msg.edit(
                embed=add_desc(msg, f"<@{payload.user_id}> Ignored")
            )
            return
        if reaction.emoji == BlackListContext.KICK:
            if not member.guild_permissions.kick_members:
                await reaction.remove(member)
                return
            await msg.clear_reaction(BlackListContext.KICK)
            if m := msg.guild.get_member(r.reported):
                await m.kick()
                await msg.edit(
                    embed=add_desc(msg, f"<@{payload.user_id}> Kicked")
                )
        if reaction.emoji == BlackListContext.BAN:
            if not member.guild_permissions.ban_members:
                await reaction.remove(member)
                return
            await msg.clear_reaction(BlackListContext.BAN)
            await guild.ban(await self.bot.fetch_user(r.reported))
            await msg.edit(
                embed=add_desc(msg, f"<@{payload.user_id}> Banned")
            )
            return
        reported = await self.bot.fetch_user(r.reported)
        if reaction.emoji == BlackListContext.PUBLIC:
            if not member.guild_permissions.ban_members:
                await reaction.remove(member)
                return
            await msg.clear_reaction(BlackListContext.PUBLIC)
            await self._ensure_guild_entry(guild)
            channel = self.bot.get_channel(self.guild_settings[guild.id][1])
            if not channel:
                return
            await channel.send(
                embed=discord.Embed(
                    title="Blacklist report",
                    description=r.reason
                )
                    .add_field(name="User", value=f"{reported} - {reported.id}")
            )
            await msg.edit(
                embed=add_desc(msg, f"<@{payload.user_id}> published")
            )


def setup(bot):
    bot.add_cog(Safety(bot))
