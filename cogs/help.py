from bot import *


class Help(commands.Cog):
    def __init__(self, bot: BlackListBot):
        self.bot = bot
        logging.info("Loaded Help")

    @property
    def description(self):
        return "Help commands"


def setup(bot):
    bot.add_cog(Help(bot))
