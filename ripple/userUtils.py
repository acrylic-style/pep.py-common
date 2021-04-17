import json
import time
try:
	from pymysql.err import ProgrammingError
except ImportError:
	from MySQLdb._exceptions import ProgrammingError


from common import generalUtils
from common.constants import gameModes
from common.constants import privileges
from common.log import logUtils as log
from common.ripple import passwordUtils, scoreUtils
from objects import glob


def getUserStats(userID, gameMode, *, relax=False):
	"""
	Get all user stats relative to `gameMode`

	:param userID:
	:param gameMode: game mode number
	:param relax: if True, return relax stats, otherwise return classic stats
	:return: dictionary with result
	"""
	modeForDB = gameModes.getGameModeForDB(gameMode)

	# Get stats
	stats = glob.db.fetch(
		f"""SELECT
		ranked_score AS rankedScore,
		accuracy_total,
		accuracy_count,
		playcount,
		total_score AS totalScore,
		rank_score AS pp
		FROM osu_user_stats{modeForDB} WHERE user_id = %s LIMIT 1""",
		(userID,)
	)

	if stats is None:
		log.info("Creating new stats data for {}".format(userID))
		res = glob.db.fetch("SELECT `country_acronym` FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
		if res is None:
			log.warning("Failed to get country for {}".format(userID))
			country = 'XX'
		else:
			country = res["country_acronym"]
		glob.db.execute(
			f"INSERT INTO osu_user_stats{modeForDB} (`user_id`, `accuracy_total`, `accuracy_count`, `accuracy`, `playcount`, `ranked_score`, `total_score`, `x_rank_count`, `s_rank_count`, `a_rank_count`, `rank`, `level`, `country_acronym`, `rank_score`, `rank_score_index`, `accuracy_new`) VALUES (%s, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, %s, 0, 0, 0)",
			(userID, country,)
		)
		return getUserStats(userID, gameMode, relax=relax)
	stats["accuracy"] = stats["accuracy_total"] / max(1, stats["accuracy_count"])
	# Get game rank
	stats["gameRank"] = getGameRank(userID, gameMode, relax=relax)

	# Return stats + game rank
	return stats

def getIDSafe(_safeUsername):
	"""
	Get user ID from a safe username
	:param _safeUsername: safe username
	:return: None if the user doesn't exist, else user id
	"""
	result = glob.db.fetch("SELECT user_id FROM phpbb_users WHERE username_clean = %s LIMIT 1", (_safeUsername,))
	if result is not None:
		return result["user_id"]
	return None

def getID(username):
	"""
	Get username's user ID from userID redis cache (if cache hit)
	or from db (and cache it for other requests) if cache miss

	:param username: user
	:return: user id or 0 if user doesn't exist
	"""
	# Get userID from redis
	usernameSafe = safeUsername(username)
	userID = glob.redis.get("ripple:userid_cache:{}".format(usernameSafe))

	if userID is None:
		# If it's not in redis, get it from mysql
		userID = getIDSafe(usernameSafe)

		# If it's invalid, return 0
		if userID is None:
			return 0

		# Otherwise, save it in redis and return it
		glob.redis.set("ripple:userid_cache:{}".format(usernameSafe), userID, 3600)	# expires in 1 hour
		return userID

	# Return userid from redis
	return int(userID)

def getUsername(userID):
	"""
	Get userID's username

	:param userID: user id
	:return: username or None
	"""
	result = glob.db.fetch("SELECT username FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if result is None:
		return None
	return result["username"]

def getSafeUsername(userID):
	"""
	Get userID's clean username

	:param userID: user id
	:return: username or None
	"""
	result = glob.db.fetch("SELECT username_clean FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if result is None:
		return None
	return result["username_clean"]

def exists(userID):
	"""
	Check if given userID exists

	:param userID: user id to check
	:return: True if the user exists, else False
	"""
	return glob.db.fetch("SELECT user_id FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,)) is not None

def checkLogin(userID, password, ip=""):
	"""
	Check userID's login with specified password

	:param userID: user id
	:param password: md5 password
	:param ip: request IP (used to check active bancho sessions). Optional.
	:return: True if user id and password combination is valid, else False
	"""
	# Check cached bancho session
	banchoSession = False
	if ip != "":
		banchoSession = checkBanchoSession(userID, ip)

	# Return True if there's a bancho session for this user from that ip
	if banchoSession:
		return True

	# Otherwise, check password
	# Get password data
	passwordData = glob.db.fetch(
		"SELECT user_password FROM phpbb_users WHERE user_id = %s LIMIT 1",
		(userID,)
	)

	# Make sure the query returned something
	if passwordData is None:
		return False

	return passwordUtils.checkNewPassword(password, passwordData["user_password"])

def getRequiredScoreForLevel(level):
	"""
	Return score required to reach a level

	:param level: level to reach
	:return: required score
	"""
	if level <= 100:
		if level >= 2:
			return 5000 / 3 * (4 * (level ** 3) - 3 * (level ** 2) - level) + 1.25 * (1.8 ** (level - 60))
		elif level <= 0 or level == 1:
			return 1  # Should be 0, but we get division by 0 below so set to 1
	elif level >= 101:
		return 26931190829 + 100000000000 * (level - 100)

def getLevel(totalScore):
	"""
	Return level from totalScore

	:param totalScore: total score
	:return: level
	"""
	level = 1
	while True:
		# if the level is > 8000, it's probably an endless loop. terminate it.
		if level > 8000:
			return level

		# Calculate required score
		reqScore = getRequiredScoreForLevel(level)

		# Check if this is our level
		if totalScore <= reqScore:
			# Our level, return it and break
			return level - 1
		else:
			# Not our level, calculate score for next level
			level += 1

def updateLevel(userID, gameMode=0, totalScore=0, *, relax=False):
	"""
	Update level in DB for userID relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:param totalScore: new total score
	:param relax:
	:return:
	"""
	# Make sure the user exists
	# if not exists(userID):
	#	return

	# Get total score from db if not passed
	mode = scoreUtils.getGameModeForDB(gameMode)
	if totalScore == 0:
		totalScore = glob.db.fetch(
			"SELECT total_score FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1".format(
				m=mode
			),
			(userID,)
		)
		if totalScore:
			totalScore = totalScore["total_score"]

	# Calculate level from totalScore
	level = getLevel(totalScore)

	# Save new level
	glob.db.execute(
		"UPDATE osu_user_stats{m} SET level = %s WHERE user_id = %s LIMIT 1".format(m=mode),
		(level, userID)
	)

def calculateAccuracy(userID, gameMode, *, relax=False):
	"""
	Calculate accuracy value for userID relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:param relax: if True, calculate relax accuracy, otherwise calculate classic accuracy
	:return: new accuracy
	"""
	gm=gameModes.getGameModeForDB(gameMode)
	# Get best accuracy scores
	stats = glob.db.fetch(
		f"""SELECT
		accuracy_total,
		accuracy_count 
		FROM osu_user_stats{gm} WHERE user_id = %s LIMIT 1""",
		(userID,)
	)
	if stats is None:
		return 0
	return stats["accuracy_total"] / stats["accuracy_count"]

def calculatePP(userID, gameMode, *, relax=False):
	"""
	Calculate userID's total PP for gameMode

	:param userID: user id
	:param gameMode: game mode number
	:param relax:
	:return: total PP
	"""
	gm = gameModes.getGameModeForDB(gameMode)
	# TODO: Check if the beatmap is pp-able
	return sum(round(round(row["pp"]) * 0.95 ** i) for i, row in enumerate(glob.db.fetchAll(
		f"SELECT pp FROM osu_scores{gm}_high "
		"WHERE user_id = %s AND "
		"pp IS NOT NULL "
		"ORDER BY pp DESC LIMIT 500",
		(userID)
	)))

def updateAccuracy(userID, gameMode, *, relax=False):
	"""
	Update accuracy value for userID relative to gameMode in DB

	:param userID: user id
	:param gameMode: gameMode number
	:param relax: if True, update relax accuracy, otherwise classic accuracy
	:return:
	"""
	newAcc = calculateAccuracy(userID, gameMode, relax=relax)
	mode = scoreUtils.getGameModeForDB(gameMode)
	glob.db.execute(
		"UPDATE osu_user_stats{m} SET accuracy = %s, accuracy_new = %s WHERE user_id = %s LIMIT 1".format(
			m=mode
		),
		(newAcc, newAcc * 100, userID)
	)

def updatePP(userID, gameMode, *, relax=False):
	"""
	Update userID's pp with new value

	:param userID: user id
	:param gameMode: game mode number
	:param relax: if True, calculate relax pp, otherwise calculate classic pp
	"""
	pp = calculatePP(userID, gameMode, relax=relax)
	gm = gameModes.getGameModeForDB(gameMode)
	glob.db.execute(
		"UPDATE osu_user_stats{} SET rank_score=%s WHERE user_id = %s LIMIT 1".format(gm),
		(pp, userID)
	)
	res = glob.db.fetch(
		"SELECT COUNT(*) AS `rank` FROM osu_user_stats{} WHERE rank_score >= %s".format(gm),
		(pp,)
	)
	if res is not None:
		# Update rank
		glob.db.execute("UPDATE osu_user_stats{} SET rank_score_index = %s WHERE user_id = %s LIMIT 1".format(gm), (res["rank"], userID))


def updateStats(userID, score_, *, relax=False):
	"""
	Update stats (playcount, total score, ranked score, level bla bla)
	with data relative to a score object

	:param userID:
	:param score_: score object
	:param relax: if True, update relax stats, otherwise classic stats
	"""

	# Make sure the user exists
	if not exists(userID):
		log.warning("User {} doesn't exist.".format(userID))
		return

	# Get gamemode for db
	mode = scoreUtils.getGameModeForDB(score_.gameMode)

	# Update total score, playcount and play time
	if score_.playTime is not None:
		realPlayTime = score_.playTime
	else:
		realPlayTime = score_.fullPlayTime

	glob.db.execute(
		"UPDATE osu_user_stats{m} SET total_score=total_score+%s, "
		"playcount=playcount+1, "
		"total_seconds_played = total_seconds_played + %s "
		"WHERE user_id = %s LIMIT 1".format(
			m=mode
		),
		(score_.score, realPlayTime, userID)
	)

	# Calculate new level and update it
	updateLevel(userID, score_.gameMode, relax=relax)

	# Update level, accuracy and ranked score only if we have passed the song
	if score_.passed:
		# Update ranked score
		glob.db.execute(
			"UPDATE osu_user_stats{m} SET ranked_score=ranked_score+%s WHERE user_id = %s LIMIT 1".format(
				m=mode
			),
			(score_.rankedScoreIncrease, userID)
		)

		# Update accuracy
		updateAccuracy(userID, score_.gameMode, relax=relax)

		# Update pp
		updatePP(userID, score_.gameMode, relax=relax)


def incrementUserBeatmapPlaycount(userID, gameMode, beatmapID):
	glob.db.execute(
		"INSERT INTO osu_user_beatmap_playcount (user_id, beatmap_id, playcount) "
		"VALUES (%s, %s, 1) ON DUPLICATE KEY UPDATE playcount = playcount + 1",
		(userID, beatmapID)
	)


def updateLatestActivity(userID):
	"""
	Update userID's latest activity to current UNIX time

	:param userID: user id
	:return:
	"""
	glob.db.execute("UPDATE phpbb_users SET user_lastvisit = %s WHERE user_id = %s LIMIT 1", (int(time.time()), userID))

def getRankedScore(userID, gameMode, *, relax=False):
	"""
	Get userID's ranked score relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:param relax:
	:return: ranked score
	"""
	mode = scoreUtils.getGameModeForDB(gameMode)
	result = glob.db.fetch(
		"SELECT ranked_score FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1".format(
			m=mode
		), (userID,)
	)
	if result is not None:
		return result["ranked_score"]
	else:
		return 0

def getPP(userID, gameMode, *, relax=False):
	"""
	Get userID's PP relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: pp
	"""

	mode = scoreUtils.getGameModeForDB(gameMode)
	result = glob.db.fetch(
		"SELECT rank_score AS pp FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1".format(
			m=mode,
		),
		(userID,)
	)
	if result is not None:
		return result["pp"]
	else:
		return 0

def incrementReplaysWatched(userID, gameMode):
	"""
	Increment userID's replays watched by others relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return:
	"""
	mode = scoreUtils.getGameModeForDB(gameMode)
	glob.db.execute(
		"UPDATE osu_user_stats{m} SET replay_popularity=replay_popularity+1 WHERE user_id = %s LIMIT 1".format(
			mode=mode
		),
		(userID,)
	)

# not used?
# def getAqn(userID):
# 	"""
# 	Check if AQN folder was detected for userID

# 	:param userID: user
# 	:return: True if hax, False if legit
# 	"""
# 	result = glob.db.fetch("SELECT user_full_folder FROM phpbb_users WHERE id = %s LIMIT 1", (userID,))
# 	if result is None:
# 		return False
# 	return int(result["user_full_folder"]) == 1

# def setAqn(userID, value=1):
# 	"""
# 	Set AQN folder status for userID

# 	:param userID: user
# 	:param value: new aqn value, default = 1
# 	:return:
# 	"""
# 	glob.db.fetch("UPDATE users SET aqn = %s WHERE id = %s LIMIT 1", (value, userID))

def IPLog(userID, ip):
	"""
	Log user IP

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	# glob.db.execute("""INSERT INTO ip_user (userid, ip, occurencies) VALUES (%s, %s, '1')
	# 					ON DUPLICATE KEY UPDATE occurencies = occurencies + 1""", (userID, ip))

def checkBanchoSession(userID, ip=""):
	"""
	Return True if there is a bancho session for `userID` from `ip`
	If `ip` is an empty string, check if there's a bancho session for that user, from any IP.

	:param userID: user id
	:param ip: ip address. Optional. Default: empty string
	:return: True if there's an active bancho session, else False
	"""
	if ip != "":
		return glob.redis.sismember("peppy:sessions:{}".format(userID), ip)
	return glob.redis.exists("peppy:sessions:{}".format(userID))

def is2FAEnabled(userID):
	"""
	Returns True if 2FA/Google auth 2FA is enable for `userID`

	:userID: user ID
	:return: True if 2fa is enabled, else False
	"""
	# return glob.db.fetch("SELECT 2fa_totp.userid FROM 2fa_totp WHERE userid = %(userid)s AND enabled = 1 LIMIT 1", {
	# 	"userid": userID
	# }) is not None

def check2FA(userID, ip):
	"""
	Returns True if this IP is untrusted.
	Returns always False if 2fa is not enabled on `userID`

	:param userID: user id
	:param ip: IP address
	:return: True if untrusted, False if trusted or 2fa is disabled.
	"""
	# if not is2FAEnabled(userID):
	# osu! does not support 2fa
	return False
	# return glob.db.fetch("SELECT id FROM ip_user WHERE userid = %s AND ip = %s LIMIT 1", (userID, ip)) is None

def isAllowed(userID):
	"""
	Check if userID is not banned or restricted

	:param userID: user id
	:return: True if not banned or restricted, otherwise false.
	"""
	result = glob.db.fetch("SELECT `user_warnings`, `user_type` FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if result is None:
		return False
	return result["user_warnings"] == 0 and result["user_type"] == 0

def isRestricted(userID):
	"""
	Check if userID is restricted

	:param userID: user id
	:return: True if not restricted, otherwise false.
	"""
	result = glob.db.fetch("SELECT user_warnings FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if result is None:
		return False
	return result["user_warnings"] == 1

def isBanned(userID):
	"""
	Check if userID is banned

	:param userID: user id
	:return: True if not banned, otherwise false.
	"""
	result = glob.db.fetch("SELECT user_type FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if result is None:
		return True
	return result["user_type"] == 1

def isLocked(userID):
	"""
	Check if userID is locked
	NOT USED, this method always return false!!! :fire: :fire: :fire:

	:param userID: user id
	:return: True if not locked, otherwise false.
	"""
	return False
	# result = glob.db.fetch("SELECT user_warnings FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	# if result is None:
	# 	return True
	# return result["user_warnings"] == 1

def ban(userID):
	"""
	Ban userID

	:param userID: user id
	:return:
	"""
	# Set user as banned in db
	banDateTime = int(time.time())
	glob.db.execute(
		"UPDATE phpbb_users SET user_type = 1 WHERE user_id = %s LIMIT 1",
		(userID)
	)

	# Notify bancho about the ban
	glob.redis.publish("peppy:ban", userID)

	# Remove the user from global and country leaderboards
	removeFromLeaderboard(userID)

def unban(userID):
	"""
	Unban userID

	:param userID: user id
	:return:
	"""
	glob.db.execute(
		"UPDATE phpbb_users SET user_type = 0 WHERE user_id = %s LIMIT 1",
		(userID)
	)
	glob.redis.publish("peppy:ban", userID)

def restrict(userID):
	"""
	Restrict userID

	:param userID: user id
	:return:
	"""
	if isRestricted(userID):
		return
	# Set user as restricted in db
	banDateTime = int(time.time())
	glob.db.execute(
		"UPDATE users SET user_warnings = 1 WHERE user_id = %s LIMIT 1",
		(userID)
	)

	# Notify bancho about this ban
	glob.redis.publish("peppy:ban", userID)

	# Remove the user from global and country leaderboards
	removeFromLeaderboard(userID)

def unrestrict(userID):
	"""
	Unrestrict userID.

	:param userID: user id
	:return:
	"""
	glob.db.execute(
		"UPDATE phpbb_users SET user_warnings = 0 WHERE user_id = %s LIMIT 1",
		(userID)
	)
	glob.redis.publish("peppy:ban", userID)

def appendNotes(userID, notes, addNl=True, trackDate=True):
	"""
	Append `notes` to `userID`'s "notes for CM"

	:param userID: user id
	:param notes: text to append
	:param addNl: Not used. (Deprecated)
	:param trackDate: Not used. (Deprecated)
	:return:
	"""
	glob.db.execute(
		"INSERT INTO osu_user_banhistory (`user_id`, `reason`, `ban_status`, `period`) values (%s, %s, 0, 0)",
		(userID, notes)
	)

# Please do not use this
# def getPrivileges(userID):
# 	"""
# 	Return `userID`'s privileges

# 	:param userID: user id
# 	:return: privileges number
# 	"""
# 	result = glob.db.fetch("SELECT `privileges` FROM users WHERE id = %s LIMIT 1", (userID,))
# 	if result is None:
# 		return 0
# 	return result["privileges"]

def getSilenceEnd(userID):
	"""
	Get userID's **ABSOLUTE** silence end UNIX time
	Remember to subtract time.time() if you want to get the actual silence time

	:param userID: user id
	:return: UNIX time
	"""
	# get latest one
	res = glob.db.fetch("SELECT `period`, `timestamp` FROM osu_user_banhistory WHERE user_id = %s AND ban_status = 2 ORDER BY `timestamp` DESC LIMIT 1", (userID,))
	if res is None:
		return 0
	return res["timestamp"] + res["period"]

def silence(userID, seconds, silenceReason, author = 999):
	"""
	Silence someone

	:param userID: user id
	:param seconds: silence length in seconds
	:param silenceReason: silence reason shown on website
	:param author: userID of who silenced the user. Default: 999
	:return:
	"""
	# db qurey
	if seconds > 0:
		glob.db.execute(
			"INSERT INTO osu_user_banhistory (`user_id`, `reason`, `ban_status`, `period`, `banner_id`) values (%s, %s, 2, %s, %s)",
			(userID, silenceReason, seconds * 1000, author)
		)
	else:
		banId = glob.db.fetch(
			"SELECT `ban_id` from osu_user_banhistory WHERE user_id = %s AND ban_status = 2 ORDER BY `timestamp` DESC LIMIT 1",
			(userID)
		)
		if banId is not None:
			glob.db.execute(
				"UPDATE osu_user_banhistory SET period = 0 WHERE ban_id = %s LIMIT 1",
				(banId)
			)

	# Log
	targetUsername = getUsername(userID)
	# TODO: exists check im drunk rn i need to sleep (stampa piede ubriaco confirmed)
	if seconds > 0:
		log.rap(author, "has silenced {} for {} seconds for the following reason: \"{}\"".format(targetUsername, seconds, silenceReason), True)
	else:
		log.rap(author, "has removed {}'s silence".format(targetUsername), True)

def getTotalScore(userID, gameMode, *, relax=False):
	"""
	Get `userID`'s total score relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:param relax:
	:return: total score
	"""
	res = glob.db.fetch(
		"SELECT total_score FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1".format(
			m=gameModes.getGameModeForDB(gameMode)
		),
		(userID,)
	)
	if res is None:
		return 0
	return res["total_score"]

def getAccuracy(userID, gameMode, *, relax=False):
	"""
	Get `userID`'s average accuracy relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:param relax:
	:return: accuracy
	"""
	m=gameModes.getGameModeForDB(gameMode)
	res = glob.db.fetch(
		f"SELECT accuracy FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1", (userID,)
	)
	if res is None:
		return 0
	return res["accuracy"]

def getGameRank(userID, gameMode, *, relax=False):
	"""
	Get `userID`'s **in-game rank** (eg: #1337) relative to gameMode

	:param userID: user id
	:param gameMode: game mode number
	:return: game rank
	"""
	# don't use this
	gm = gameModes.getGameModeForDB(gameMode)
	res = glob.db.fetch(
		"SELECT `rank_score_index` FROM osu_user_stats{m} WHERE user_id = %s".format(
			m=gm
		), (userID,)
	)
	if res is None:
		return 0
	return res["rank_score_index"]
	# k = "ripple:leaderboard:{}".format(gameModes.getGameModeForDB(gameMode))
	# if relax:
	# 	k += ":relax"
	# position = glob.redis.zrevrank(k, userID)
	# if position is None:
	# 	return 0
	# else:
	# 	return int(position) + 1

def getPlaycount(userID, gameMode, *, relax=False):
	"""
	Get `userID`'s playcount relative to `gameMode`

	:param userID: user id
	:param gameMode: game mode number
	:param relax:
	:return: playcount
	"""
	res = glob.db.fetch(
		"SELECT playcount FROM osu_user_stats{m} WHERE user_id = %s LIMIT 1".format(
			m=gameModes.getGameModeForDB(gameMode),
		),
		(userID,)
	)
	if res is None:
		return 0
	return res["playcount"]

def getFriendList(userID):
	"""
	Get `userID`'s friendlist

	:param userID: user id
	:return: list with friends userIDs. [0] if no friends.
	"""
	# Get friends from db
	friends = glob.db.fetchAll("SELECT zebra_id FROM phpbb_zebra WHERE user_id = %s AND friend = 1", (userID,))

	if friends is None or len(friends) == 0:
		# We have no friends, return 0 list
		return [0]
	else:
		# Get only friends
		friends = [i["zebra_id"] for i in friends]

		# Return friend IDs
		return friends

def addFriend(userID, friendID):
	"""
	Add `friendID` to `userID`'s friend list

	:param userID: user id
	:param friendID: new friend
	:return:
	"""
	# Make sure we aren't adding us to our friends
	if userID == friendID:
		return

	# check user isn't already a friend of ours
	res = glob.db.fetch("SELECT friend FROM phpbb_zebra WHERE user_id = %s AND zebra_id = %s LIMIT 1", [userID, friendID])
	if res is None:
		# Set new value
		glob.db.execute("INSERT INTO phpbb_zebra (user_id, zebra_id, friend, foe) VALUES (%s, %s, 1, 0)", [userID, friendID])
	elif res["friend"] != 1:
		# just update friend value
		glob.db.execute("UPDATE phpbb_zebra SET friend = 1 WHERE user_id = %s, zebra_id = %s", [userID, friendID])

def removeFriend(userID, friendID):
	"""
	Remove `friendID` from `userID`'s friend list

	:param userID: user id
	:param friendID: old friend
	:return:
	"""
	# Delete user relationship. We don't need to check if the relationship was there, because who gives a shit,
	# if they were not friends and they don't want to be anymore, be it. ¯\_(ツ)_/¯
	glob.db.execute("DELETE FROM phpbb_zebra WHERE user_id = %s AND zebra_id = %s LIMIT 1", (userID, friendID))


def getCountry(userID):
	"""
	Get `userID`'s country **(two letters)**.

	:param userID: user id
	:return: country code (two letters)
	"""
	res = glob.db.fetch("SELECT country_acronym FROM osu_user_stats WHERE user_id = %s LIMIT 1", (userID,))
	if res is None:
		return "XX"
	return res["country_acronym"]

def setCountry(userID, country):
	"""
	Set userID's country

	:param userID: user id
	:param country: country letters
	:return:
	"""
	glob.db.execute("UPDATE phpbb_users SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats_taiko SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats_fruits SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats_mania SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats_mania_4k SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))
	glob.db.execute("UPDATE osu_user_stats_mania_7k SET country_acronym = %s WHERE user_id = %s LIMIT 1", (country, userID))

def logIP(userID, ip):
	"""
	User IP log
	USED FOR MULTIACCOUNT DETECTION

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	# glob.db.execute("""INSERT INTO ip_user (userid, ip, occurencies) VALUES (%s, %s, 1)
	# 					ON DUPLICATE KEY UPDATE occurencies = occurencies + 1""", [userID, ip])

def saveBanchoSession(userID, ip):
	"""
	Save userid and ip of this token in redis
	Used to cache logins on LETS requests

	:param userID: user ID
	:param ip: IP address
	:return:
	"""
	glob.redis.sadd("peppy:sessions:{}".format(userID), ip)

def deleteBanchoSessions(userID, ip):
	"""
	Delete this bancho session from redis

	:param userID: user id
	:param ip: IP address
	:return:
	"""
	glob.redis.srem("peppy:sessions:{}".format(userID), ip)

def setPrivileges(userID, priv):
	"""
	Set userID's privileges in db

	:param userID: user id
	:param priv: privileges number
	:return:
	"""
	gid = glob.db.fetch("SELECT `group_id` FROM phpbb_user_group WHERE group_id = %s AND user_id = %s LIMIT 1", (priv, userID))
	if gid is None:
		glob.db.execute("INSERT INTO phpbb_user_group (`group_id`, `user_id`, `group_leader`, `user_pending`, `playmodes`) values (%s, %s, 0, 0, NULL)", (priv, userID))

def getGroupPrivileges(groupName):
	"""
	Returns the privileges number of a group, by its name

	:param groupName: name of the group
	:return: privilege integer or `None` if the group doesn't exist
	"""
	groupPrivileges = glob.db.fetch(
		"SELECT `group_id` FROM phpbb_groups WHERE `identifier` = %s LIMIT 1",
		(groupName,)
	)
	if groupPrivileges is None:
		return None
	return groupPrivileges["group_id"]

def isInPrivilegeGroup(userID, groupName):
	"""
	Check if `userID` is in a privilege group.
	Donor privilege is ignored while checking for groups.

	:param userID: user id
	:param groupName: privilege group name
	:return: True if `userID` is in `groupName`, else False
	"""
	groupPrivileges = getGroupPrivileges(groupName)
	if groupPrivileges is None:
		return False
	gid = glob.db.fetch(
		"SELECT `group_id` FROM phpbb_user_group WHERE `user_id` = %s AND `group_id` = %s LIMIT 1",
		(userID, groupPrivileges,)
	)
	return gid is not None

def isSupporter(userID):
	subscriber = glob.db.fetch(
		"SELECT `osu_subscriber` FROM phpbb_users WHERE `user_id` = %s",
		(userID,)
	)
	if subscriber is None:
		return False
	return subscriber == 1

def isInPrivilegeGroupId(userID, groupId):
	"""
	Check if `userID` is in a privilege group.
	Donor privilege is ignored while checking for groups.

	:param userID: user id
	:param groupId: group id to check
	:return: True if `userID` is in `groupId`, else False
	"""
	gid = glob.db.fetch(
		"SELECT `group_id` FROM phpbb_user_group WHERE `user_id` = %s AND `group_id` = %s LIMIT 1",
		(userID, groupId,)
	)
	return gid is not None

def isInAnyPrivilegeGroup(userID, groups):
	"""
	Checks if a user is in at least one of the specified groups

	:param userID: id of the user
	:param groups: groups list or tuple
	:return: `True` if `userID` is in at least one of the specified groups, otherwise `False`
	"""
	
	gids = glob.db.fetchAll("SELECT `group_id` FROM phpbb_user_group WHERE `user_id` = %s", (userID))
	for g1 in gids:
		for g in groups:
			g2 = glob.db.fetch("SELECT `group_id` FROM phpbb_groups WHERE `identifier` = %s", (g))
			if g1 == g2:
				return True
	return False

def logHardware(userID, hashes, activation = False):
	"""
	Hardware log
	USED FOR MULTIACCOUNT DETECTION


	:param userID: user id
	:param hashes:	Peppy's botnet (client data) structure (new line = "|", already split)
					[0] osu! version
					[1] plain mac addressed, separated by "."
					[2] mac addresses hash set
					[3] unique ID
					[4] disk ID
	:param activation: if True, set this hash as used for activation. Default: False.
	:return: True if hw is not banned, otherwise false
	"""
	# Make sure the strings are not empty
	for i in hashes[2:5]:
		if i == "":
			log.warning("Invalid hash set ({}) for user {} in HWID check".format(hashes, userID), "bunk")
			return False

	# Run some HWID checks on that user if they are not restricted
	if not isRestricted(userID):
		# Get username
		username = getUsername(userID)

		# Get the list of banned or restricted users that have logged in from this or similar HWID hash set
		if hashes[2] == "b4ec3c4334a0249dae95c284ec5983df":
			# Running under wine, check by unique id
			log.debug("Logging Linux/Mac hardware")
			banned = glob.db.fetchAll("""SELECT phpbb_users.user_id as userid, hw_user.occurencies, phpbb_users.username FROM hw_user
				LEFT JOIN phpbb_users ON phpbb_users.user_id = hw_user.userid
				WHERE hw_user.userid != %(userid)s
				AND hw_user.unique_id = %(uid)s
				AND (phpbb_users.user_warnings = 1 OR phpbb_users.user_type = 1)""", {
					"userid": userID,
					"uid": hashes[3],
				})
		else:
			# Running under windows, do all checks
			log.debug("Logging Windows hardware")
			banned = glob.db.fetchAll("""SELECT phpbb_users.user_id as userid, hw_user.occurencies, phpbb_users.username FROM hw_user
				LEFT JOIN phpbb_users ON phpbb_users.user_id = hw_user.userid
				WHERE hw_user.userid != %(userid)s
				AND hw_user.mac = %(mac)s
				AND hw_user.unique_id = %(uid)s
				AND hw_user.disk_id = %(diskid)s
				AND (phpbb_users.user_warnings = 1 OR phpbb_users.user_type = 1)""", {
					"userid": userID,
					"mac": hashes[2],
					"uid": hashes[3],
					"diskid": hashes[4],
				})

		for i in banned:
			# Get the total numbers of logins
			total = glob.db.fetch("SELECT COUNT(*) AS `count` FROM hw_user WHERE userid = %s LIMIT 1", [userID])
			# and make sure it is valid
			if total is None:
				continue
			total = total["count"]

			# Calculate 10% of total
			perc = (total*10)/100

			if i["occurencies"] >= perc:
				# If the banned user has logged in more than 10% of the times from this user, restrict this user
				restrict(userID)
				appendNotes(userID, "Auto Restricted: Logged in from HWID ({hwid}) used more than 10% from user {banned} ({bannedUserID}), who is banned/restricted.".format(
					hwid=hashes[2:5],
					banned=i["username"],
					bannedUserID=i["userid"]
				))
				log.cm(
					"**{user}** ({userID}) has been restricted because they have logged in from HWID "
					"({hwid})_used more than 10% from banned/restricted user **{banned}** ({bannedUserID}), "
					"**possible multiaccount**.".format(
						user=username,
						userID=userID,
						hwid=hashes[2:5],
						banned=i["username"],
						bannedUserID=i["userid"]
					)
				)

	# Update hash set occurencies
	glob.db.execute("""
				INSERT INTO hw_user (id, userid, mac, unique_id, disk_id, occurencies) VALUES (NULL, %s, %s, %s, %s, 1)
				ON DUPLICATE KEY UPDATE occurencies = occurencies + 1
				""", [userID, hashes[2], hashes[3], hashes[4]])

	# Optionally, set this hash as 'used for activation'
	if activation:
		glob.db.execute("UPDATE hw_user SET activated = 1 WHERE userid = %s AND mac = %s AND unique_id = %s AND disk_id = %s", [userID, hashes[2], hashes[3], hashes[4]])

	# Access granted, abbiamo impiegato 3 giorni
	# We grant access even in case of login from banned HWID
	# because we call restrict() above so there's no need to deny the access.
	return True


def resetPendingFlag(userID, success=True):
	"""
	Remove pending flag from an user.

	:param userID: user id
	:param success: if True, set USER_PUBLIC and USER_NORMAL flags too
	"""
	glob.db.execute(
		"UPDATE phpbb_user_group SET user_pending = 0 WHERE user_id = %s AND user_pending = 1",
		(userID,)
	)
	if success:
		gid = getGroupPrivileges("default")
		if gid is not None:
			glob.db.execute(
				"INSERT IGNORE INTO phpbb_user_group (`group_id`, `user_id`, `group_leader`, `user_pending`, `playmodes`) values (%s, %s, 0, 0, NULL)",
				(gid, userID)
			)

def verifyUser(userID, hashes):
	"""
	Activate `userID`'s account.

	:param userID: user id
	:param hashes: 	Peppy's botnet (client data) structure (new line = "|", already split)
					[0] osu! version
					[1] plain mac addressed, separated by "."
					[2] mac addresses hash set
					[3] unique ID
					[4] disk ID
	:return: True if verified successfully, else False (multiaccount)
	"""
	# Check for valid hash set
	for i in hashes[2:5]:
		if i == "":
			log.warning("Invalid hash set ({}) for user {} while verifying the account".format(str(hashes), userID), "bunk")
			return False

	# Get username
	username = getUsername(userID)

	# Make sure there are no other accounts activated with this exact mac/unique id/hwid
	if hashes[2] == "b4ec3c4334a0249dae95c284ec5983df" or hashes[4] == "ffae06fb022871fe9beb58b005c5e21d":
		# Running under wine, check only by uniqueid
		log.info("{user} ({userID}) is using wine, checking only by unique id:\n**Full data:** {hashes}\n**Usual wine mac address hash:** b4ec3c4334a0249dae95c284ec5983df\n**Usual wine disk id:** ffae06fb022871fe9beb58b005c5e21d".format(user=username, userID=userID, hashes=hashes), "bunker")
		log.debug("Verifying with Linux/Mac hardware")
		match = glob.db.fetchAll("SELECT userid FROM hw_user WHERE unique_id = %(uid)s AND userid != %(userid)s AND activated = 1 LIMIT 1", {
			"uid": hashes[3],
			"userid": userID
		})
	else:
		# Running under windows, full check
		log.debug("Veryfing with Windows hardware")
		match = glob.db.fetchAll("SELECT userid FROM hw_user WHERE mac = %(mac)s AND unique_id = %(uid)s AND disk_id = %(diskid)s AND userid != %(userid)s AND activated = 1 LIMIT 1", {
			"mac": hashes[2],
			"uid": hashes[3],
			"diskid": hashes[4],
			"userid": userID
		})

	if match:
		# This is a multiaccount, restrict other account and ban this account

		# Get original userID and username (lowest ID)
		originalUserID = match[0]["userid"]
		originalUsername = getUsername(originalUserID)

		# Ban this user and append notes
		ban(userID)	# this removes the USER_PENDING_VERIFICATION flag too
		appendNotes(userID, "{}'s multiaccount ({}), found HWID match while verifying account ({})".format(originalUsername, originalUserID, hashes[2:5]))
		appendNotes(originalUserID, "Has created multiaccount {} ({})".format(username, userID))

		# Restrict the original
		restrict(originalUserID)

		# Discord message
		log.cm(
			"User **{originalUsername}** ({originalUserID}) has been restricted because "
			"they have created multiaccount **{username}** ({userID}). "
			"The multiaccount has been banned.".format(
				originalUsername=originalUsername,
				originalUserID=originalUserID,
				username=username,
				userID=userID
			)
		)

		# Disallow login
		return False
	else:
		# No matches found, set USER_PUBLIC and USER_NORMAL flags and reset USER_PENDING_VERIFICATION flag
		resetPendingFlag(userID)
		#log.cm("User **{}** ({}) has verified his account with hash set _{}_".format(username, userID, hashes[2:5]))

		# Allow login
		return True

def hasVerifiedHardware(userID):
	"""
	Checks if `userID` has activated his account through HWID

	:param userID: user id
	:return: True if hwid activation data is in db, otherwise False
	"""
	return glob.db.fetch("SELECT id FROM hw_user WHERE userid = %s AND activated = 1 LIMIT 1", (userID,)) is not None

def getDonorExpire(userID):
	"""
	Return `userID`'s donor expiration UNIX timestamp

	:param userID: user id
	:return: donor expiration UNIX timestamp
	"""
	data = glob.db.fetch("SELECT osu_subscriptionexpiry FROM phpbb_users WHERE user_id = %s LIMIT 1", (userID,))
	if data is not None:
		return int(time.mktime(time.strptime(data["osu_subscriptionexpiry"], "%Y-%m-%d %H:%M:%S"))*1000)
	return 0


class invalidUsernameError(Exception):
	pass

class usernameAlreadyInUseError(Exception):
	pass

def safeUsername(username):
	"""
	Return `username`'s safe username
	(all lowercase and underscores instead of spaces)

	:param username: unsafe username
	:return: safe username
	"""
	return username.lower().strip().replace(" ", "_")

def changeUsername(userID=0, oldUsername="", newUsername=""):
	"""
	Change `userID`'s username to `newUsername` in database

	:param userID: user id. Required only if `oldUsername` is not passed.
	:param oldUsername: username. Required only if `userID` is not passed.
	:param newUsername: new username. Can't contain spaces and underscores at the same time.
	:raise: invalidUsernameError(), usernameAlreadyInUseError()
	:return:
	"""
	# Make sure new username doesn't have mixed spaces and underscores
	if " " in newUsername and "_" in newUsername:
		raise invalidUsernameError()
	if len(newUsername) > 30:
		raise invalidUsernameError()

	# Get safe username
	newUsernameSafe = safeUsername(newUsername)

	# Make sure this username is not already in use
	if getIDSafe(newUsernameSafe) is not None:
		raise usernameAlreadyInUseError()

	# Get userID or oldUsername
	if userID == 0:
		userID = getID(oldUsername)
	else:
		oldUsername = getUsername(userID)

	# Change username
	glob.db.execute(
		"UPDATE phpbb_users SET username = %s, username_clean = %s, username_previous = %s WHERE user_id = %s LIMIT 1",
		(newUsername, newUsernameSafe, oldUsername, userID)
	)
	glob.db.execute(
		"INSERT INTO osu_username_change_history (`user_id`, `username`, `type`, `username_last`) values (%s, %s, 'paid', %s)",
		(userID, newUsername, oldUsername)
	)

	# Empty redis username cache
	# TODO: Le pipe woo woo
	glob.redis.delete("ripple:userid_cache:{}".format(safeUsername(oldUsername)))
	glob.redis.delete("ripple:change_username_pending:{}".format(userID))

def removeFromLeaderboard(userID):
	"""
	Removes userID from global and country leaderboards.

	:param userID:
	:return:
	"""
	# Remove the user from global and country leaderboards, for every mode
	country = getCountry(userID).lower()
	for mode in ("std", "taiko", "ctb", "mania"):
		for suffix in ("", ":relax"):
			glob.redis.zrem("ripple:leaderboard:{}{}".format(mode, suffix), str(userID))
			if country is not None and len(country) > 0 and country != "xx":
				glob.redis.zrem("ripple:leaderboard:{}:{}{}".format(mode, country, suffix), str(userID))

# Not used / Don't use this
# def deprecateTelegram2Fa(userID):
# 	"""
# 	Checks whether the user has enabled telegram 2fa on his account.
# 	If so, disables 2fa and returns True.
# 	If not, return False.

# 	:param userID: id of the user
# 	:return: True if 2fa has been disabled from the account otherwise False
# 	"""
# 	try:
# 		telegram2Fa = glob.db.fetch("SELECT id FROM 2fa_telegram WHERE userid = %s LIMIT 1", (userID,))
# 	except ProgrammingError:
# 		# The table doesnt exist
# 		return False

# 	if telegram2Fa is not None:
# 		glob.db.execute("DELETE FROM 2fa_telegram WHERE userid = %s LIMIT 1", (userID,))
# 		return True
# 	return False

def unlockAchievement(userID, achievementID):
	glob.db.execute(
		"INSERT IGNORE INTO osu_user_achievements (user_id, achievement_id) VALUES (%s, %s)",
		(userID, achievementID)
	)

# def getAchievementsVersion(userID):
# 	result = glob.db.fetch("SELECT achievements_version FROM users WHERE id = %s LIMIT 1", (userID,))
# 	if result is None:
# 		return None
# 	return result["achievements_version"]

# def updateAchievementsVersion(userID):
# 	glob.db.execute("UPDATE users SET achievements_version = %s WHERE id = %s LIMIT 1", (
# 		glob.ACHIEVEMENTS_VERSION, userID
# 	))

def updateTotalHits(userID=0, gameMode=gameModes.STD, newHits=0, score=None, *, relax=False):
	if score is None and userID == 0:
		raise ValueError("Either score or userID must be provided")
	if score is not None:
		newHits = score.c50 + score.c100 + score.c300
		gameMode = score.gameMode
		userID = score.playerUserID
		gm=gameModes.getGameModeForDB(gameMode)
		glob.db.execute(
			f"UPDATE osu_user_stats{gm} SET count300 = count300 + %s, count100 = count100 + %s, count50 = count50 + %s, countMiss = countMiss + %s WHERE user_id = %s LIMIT 1",
			(score.c300, score.c100, score.c50, score.cMiss, userID)
		)

def isRelaxLeaderboard(userID):
	return False

# Not used
# def _get_pref(userID, column):
# 	return glob.db.fetch(f"SELECT {column} AS x FROM users_preferences WHERE id = %s LIMIT 1", (userID,))["x"]


def getDisplayMode(userID, relax):
	# score
	return 0

def getAutoLast(userID, relax):
	# notification
	return 2

def getScoreOverwrite(userID, gameMode):
	# score
	return 1
