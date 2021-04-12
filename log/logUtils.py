import logging
import sys

from common.constants import bcolors
from common import generalUtils

import time
import os

ENDL = "\n" if os.name == "posix" else "\r\n"

def logMessage(message, alertType = "INFO", messageColor = bcolors.ENDC, discord = None, alertDev = False, of = None, stdout = True):
	"""
	Log a message

	:param message: message to log
	:param alertType: alert type string. Can be INFO, WARNING, ERROR or DEBUG. Default: INFO
	:param messageColor: message console ANSI color. Default: no color
	:param discord: Discord channel acronym for Schiavo. If None, don't log to Discord. Default: None
	:param alertDev: 	if True, developers will be highlighted on Discord.
						Obviously works only if the message will be logged to Discord.
						Default: False
	:param of:	Output file name (inside .data folder). If None, don't log to file. Default: None
	:param stdout: If True, log to stdout (print). Default: True
	:return:
	"""
	# Get type color from alertType
	if alertType == "INFO":
		typeColor = bcolors.GREEN
	elif alertType == "WARNING":
		typeColor = bcolors.YELLOW
	elif alertType == "ERROR":
		typeColor = bcolors.RED
	elif alertType == "CHAT":
		typeColor = bcolors.BLUE
	elif alertType == "DEBUG":
		typeColor = bcolors.PINK
	else:
		typeColor = bcolors.ENDC

	# Message without colors
	finalMessage = "[{time}] {type} - {message}".format(time=generalUtils.getTimestamp(), type=alertType, message=message)

	# Message with colors
	finalMessageConsole = "{typeColor}[{time}] {type}{endc} - {messageColor}{message}{endc}".format(
		time=generalUtils.getTimestamp(),
		type=alertType,
		message=message,

		typeColor=typeColor,
		messageColor=messageColor,
		endc=bcolors.ENDC)

	# Log to console
	if stdout:
		print(finalMessageConsole)
		sys.stdout.flush()

	# Log to discord if needed
	if discord is not None:
		if discord == "bunker":
			glob.schiavo.sendConfidential(message, alertDev)
		elif discord == "cm":
			glob.schiavo.sendCM(message)
		elif discord == "staff":
			glob.schiavo.sendStaff(message)
		elif discord == "general":
			glob.schiavo.sendGeneral(message)

	# Log to file if needed
	if of is not None:
		glob.fileBuffers.write(".data/"+of, finalMessage+ENDL)

def discord(channel, message, level=None):
	import objects.glob

	if channel == "bunker":
		objects.glob.schiavo.sendConfidential(message)
	elif channel == "cm":
		objects.glob.schiavo.sendCM(message)
	elif channel == "staff":
		objects.glob.schiavo.sendStaff(message)
	elif channel == "general":
		objects.glob.schiavo.sendGeneral(message)
	else:
		raise ValueError("Unsupported channel ({})".format(channel))

	# Log with stdlib logging
	if level is not None:
		LEVELS_MAPPING.get(level.lower(), info)(message)


def cm(message):
	"""
	CM logging (to discord and with logging)

	:param message: the message to log
	:return:
	"""
	return discord("cm", message, level="warning")


def warning(message):
	logging.warning(message)


def error(message):
	logging.error(message)


def info(message):
	logging.info(message)


def debug(message):
	logging.debug(message)

def chat(message):
	"""
	Log a public chat message to stdout and to chatlog_public.txt.

	:param message: message content
	:return:
	"""
	logMessage(message, "CHAT", bcolors.BLUE, of="chatlog_public.txt")


def rap(userID, message, discordChannel=None, through="FokaBot"):
	"""
	Log a message to Admin Logs.

	:param userID: admin user ID
	:param message: message content, without username
	:param discordChannel: discord channel to send this message to or None to disable discord logging
	:param through: through string. Default: FokaBot
	:return:
	"""
	import common.ripple
	#import objects.glob
	#objects.glob.db.execute("INSERT INTO rap_logs (id, userid, text, datetime, through) VALUES (NULL, %s, %s, %s, %s)", [userID, message, int(time.time()), through])
	username = common.ripple.userUtils.getUsername(userID)
	if discordChannel is not None:
		discord(discordChannel, "{} {}".format(username, message))

LEVELS_MAPPING = {
	"warning": warning,
	"info": info,
	"error": error
}