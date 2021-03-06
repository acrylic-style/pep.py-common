STD = 0
TAIKO = 1
CTB = 2
MANIA = 3

_MODE_FROM_DB = {
	"std": STD,
	"taiko": TAIKO,
	"ctb": CTB,
	"mania": MANIA
}

def getGameModeForDB(gameMode):
	"""
	Convert a game mode number to string for database table/column

	:param gameMode: game mode number
	:return: game mode readable string for db
	"""

	if gameMode == STD:
		return ""
	elif gameMode == TAIKO:
		return "_taiko"
	elif gameMode == CTB:
		return "_fruits"
	else:
		return "_mania"

def getGamemodeFull(gameMode):
	"""
	Get game mode name from game mode number

	:param gameMode: game mode number
	:return: game mode readable name
	"""
	if gameMode == STD:
		return "osu!"
	elif gameMode == TAIKO:
		return "Taiko"
	elif gameMode == CTB:
		return "Catch The Beat"
	else:
		return "osu!mania"

def getGameModeForPrinting(gameMode):
	"""
	Convert a gamemode number to string for showing to a user (e.g. !last)

	:param gameMode: gameMode int or variable (ex: gameMode.std)
	:return: game mode readable string for a human
	"""
	if gameMode == STD:
		return "osu!"
	elif gameMode == TAIKO:
		return "Taiko"
	elif gameMode == CTB:
		return "CatchTheBeat"
	else:
		return "osu!mania"


def getGameModeFromDB(s):
	try:
		return _MODE_FROM_DB[s]
	except KeyError:
		return None


def getSafeGameMode(gameMode: int):
	if gameMode == STD:
		return "osu"
	elif gameMode == TAIKO:
		return "taiko"
	elif gameMode == CTB:
		return "fruits"
	else:
		return "mania"


def getWebGameMode(gameMode: int):
	if gameMode == STD:
		return "osu!"
	elif gameMode == TAIKO:
		return "osu!taiko"
	elif gameMode == CTB:
		return "osu!catch"
	else:
		return "osu!mania"
