import logging
import os

import dotenv

from bot import BlackListBot

dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO)

bot = BlackListBot(command_prefix="bl!", help_command=None)

extensions = {
    "Hidden": {
        "cogs.safety": "Safety"
    },
    "Misc": {
        "cogs.help": "Help"
    }
}

for grp_name, ext_set in extensions.items():
    for path, cog_name in ext_set.items():
        logging.info(f"cog:Loading {grp_name}:{cog_name} from {path}")
        bot.load_extension(path)
        bot.set_cog_group(cog_name, grp_name)

bot.run(os.getenv("TOKEN"))
