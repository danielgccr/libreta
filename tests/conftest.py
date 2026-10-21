import os

# The tests check the Spanish messages, whatever the language of the machine (libreta.i18n
# reads it on import, and workers inherit it).
os.environ["LIBRETA_LANG"] = "es"
