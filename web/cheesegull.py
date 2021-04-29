import time

def toDirect(data):
	if len(data) == 0:
		return ""
	s = "{beatmapset_id}.osz|{artist}|{title}|{creator}|{approved}|{rating}|{lastUpdate}|{beatmapset_id}|" \
		"{beatmapset_id}|{HasVideoInt}|1|1337|{FileSizeNoVideo}|".format(
			**data[0],
			**{
				"lastUpdate": int(time.mktime(
					time.strptime(
						data[0]["last_update"] if data[0]["approved_date"] is None else data[0]["approved_date"],
						"%Y-%m-%d %H:%M:%S")) * 1000),
				"HasVideoInt": int(data[0]["video"]),
				"FileSizeNoVideo": "7331" if int(data[0]["video"]) == 1 else ""
			}
		)
	for i in data:
		s += \
			"{DiffNameSanitized} ({difficultyrating:.2f}★~{bpm}♫~AR{diff_approach}~OD{diff_overall}~CS{diff_size}~HP{diff_drain}~{ReadableLength})" \
			"@{playmode},".format(
				**i,
				**{
					"DiffNameSanitized": i["version"].replace("@", "").replace("|", "-"),
					"ReadableLength": "{}m{}s".format(i["total_length"] // 60, i["total_length"] % 60)
				}
			)
	s = s.strip(",")
	s += "|"
	return s


def toDirectNp(data):
	return "{beatmapset_id}.osz|{artist}|{title}|{creator}|{approved}|{rating}|{lastUpdate}|{beatmapset_id}|" \
		"{beatmapset_id}|{video}|1|1337|{FileSizeNoVideo}".format(
		**data,
		**{
			"lastUpdate": int(time.mktime(
				time.strptime(
					data[0]["last_update"] if data[0]["approved_date"] is None else data[0]["approved_date"],
					"%Y-%m-%d %H:%M:%S")) * 1000),
			"video": int(data["video"]),
			"FileSizeNoVideo": "7331" if int(data["video"]) == 1 else ""
		}
	)


def directToApiStatus(directStatus):
	if directStatus is None:
		return None
	elif directStatus == 0 or directStatus == 7:
		# 1, 2
		return 999
	elif directStatus == 8:
		return 4
	elif directStatus == 3:
		return 3
	elif directStatus == 2:
		return 0
	elif directStatus == 5:
		return -2
	elif directStatus == 4:
		return None
	else:
		return 1
