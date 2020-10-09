from bot import *


class EntranceWarning(commands.Cog):
    def __init__(self, bot: BlackListBot):
        self.bot = bot
        logging.info("Loaded EntranceWarning")

    @property
    def description(self):
        return "Entrance Warning commands"


def setup(bot):
    bot.add_cog(EntranceWarning(bot))
