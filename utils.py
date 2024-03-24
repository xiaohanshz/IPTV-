import aiohttp
import asyncio
import config
import time
import re
import datetime
import os
import urllib.parse
import ipaddress

async def play_and_filter_url(url):
    """
    Test playback of a live stream URL for the specified duration and filter URLs based on playback smoothness.
    """
    if any(re.match(pattern, url) for pattern in config.filter_url):
        print(f"Skipping URL {url} due to filtering.")
        return False

    command = [
        "ffplay",
        "-nodisp",  # Disable video display
        "-loglevel",
        "panic",  # Suppress FFmpeg console output
        "-timeout",
        str(config.url_time),  # Timeout specified by config
        url,
    ]
    process = await asyncio.create_subprocess_exec(*command)
    try:
        await asyncio.wait_for(process.wait(), timeout=config.url_time)
        # If the process finishes within the specified time, the URL is smooth
        return True
    except asyncio.TimeoutError:
        # If the process doesn't finish within the specified time, the URL is not smooth
        return False
    except Exception as e:
        print(f"Error while playing URL {url}: {e}")
        return False

async def filterByPlayback(url_list):
    """
    Filter URLs based on playback smoothness and urls_limit.
    """
    valid_urls = []
    filtered_urls = [url for url in url_list if not any(re.match(pattern, url) for pattern in config.filter_url)]
    for url in filtered_urls:
        if await play_and_filter_url(url):
            valid_urls.append(url)
        if len(valid_urls) >= config.urls_limit:
            break
    return valid_urls


def getChannelItems():
    """
    Get the channel items from the source file
    """
    # Open the source file and read all lines.
    with open(config.source_file, "r") as f:
        lines = f.readlines()

    # Create a dictionary to store the channels.
    channels = {}
    current_channel = ""
    pattern = r"^(.*?),(?!#genre#)(.*?)$"

    for line in lines:
        line = line.strip()
        if "#genre#" in line:
            # This is a new channel, create a new key in the dictionary.
            current_channel = line.split(",")[0]
            channels[current_channel] = {}
        else:
            # This is a url, add it to the list of urls for the current channel.
            match = re.search(pattern, line)
            if match:
                if match.group(1) not in channels[current_channel]:
                    channels[current_channel][match.group(1)] = [match.group(2)]
                else:
                    channels[current_channel][match.group(1)].append(match.group(2))
    return channels


def updateChannelUrlsM3U(cate, channelUrls):
    """
    Update the category and channel urls to the final file in M3U format
    """
    with open("live_new.m3u", "a") as f:
        f.write("#EXTM3U\n")
        for name, urls in channelUrls.items():
            for url in urls:
                if url is not None:
                    f.write(f"#EXTINF:-1 tvg-id=\"\" tvg-name=\"{name}\" tvg-logo=\"https://gitee.com/yuanzl77/TVBox-logo/raw/main/png/{name}.png\" group-title=\"{cate}\",{name}\n")
                    f.write(url + "\n")
        f.write("\n")


def updateFile(final_file, old_file):
    """
    Update the file
    """
    if os.path.exists(final_file):
        os.remove(final_file)
    if os.path.exists(old_file):
        os.rename(old_file, final_file)


def getUrlInfo(result):
    """
    Get the url, date and resolution
    """
    m3u8_div = result.find("div", class_="m3u8")
    url = m3u8_div.text.strip() if m3u8_div else None
    info_div = m3u8_div.find_next_sibling("div") if m3u8_div else None
    date = resolution = None
    if info_div:
        info_text = info_div.text.strip()
        date, resolution = (
            (info_text.partition(" ")[0] if info_text.partition(" ")[0] else None),
            (
                info_text.partition(" ")[2].partition("•")[2]
                if info_text.partition(" ")[2].partition("•")[2]
                else None
            ),
        )
    return url, date, resolution


async def getSpeed(url):
    """
    Get the speed of the url
    """
    async with aiohttp.ClientSession() as session:
        start = time.time()
        try:
            async with session.get(url, timeout=5) as response:
                resStatus = response.status
        except:
            return float("inf")
        end = time.time()
        if resStatus == 200:
            return int(round((end - start) * 1000))
        else:
            return float("inf")


async def compareSpeedAndResolution(infoList):
    """
    Sort by speed and resolution
    """
    response_times = await asyncio.gather(*(getSpeed(url) for url, _, _ in infoList))
    valid_responses = [
        (info, rt) for info, rt in zip(infoList, response_times) if rt != float("inf")
    ]

    def extract_resolution(resolution_str):
        numbers = re.findall(r"\d+x\d+", resolution_str)
        if numbers:
            width, height = map(int, numbers[0].split("x"))
            return width * height
        else:
            return 0

    default_response_time_weight = 0.5
    default_resolution_weight = 0.5
    response_time_weight = getattr(
        config, "response_time_weight", default_response_time_weight
    )
    resolution_weight = getattr(config, "resolution_weight", default_resolution_weight)
    # Check if weights are valid
    if not (
        0 <= response_time_weight <= 1
        and 0 <= resolution_weight <= 1
        and response_time_weight + resolution_weight == 1
    ):
        response_time_weight = default_response_time_weight
        resolution_weight = default_resolution_weight

    def combined_key(item):
        (_, _, resolution), response_time = item
        resolution_value = extract_resolution(resolution) if resolution else 0
        return (
            -(response_time_weight * response_time)
            + resolution_weight * resolution_value
        )

    sorted_res = sorted(valid_responses, key=combined_key, reverse=True)
    return sorted_res


def filterByDate(data):
    """
    Filter by date and limit
    """
    default_recent_days = 60
    use_recent_days = getattr(config, "recent_days", 60)
    if (
        not isinstance(use_recent_days, int)
        or use_recent_days <= 0
        or use_recent_days > 365
    ):
        use_recent_days = default_recent_days
    start_date = datetime.datetime.now() - datetime.timedelta(days=use_recent_days)
    recent_data = []
    unrecent_data = []
    for (url, date, resolution), response_time in data:
        if date:
            date = datetime.datetime.strptime(date, "%m-%d-%Y")
            if date >= start_date:
                recent_data.append(((url, date, resolution), response_time))
            else:
                unrecent_data.append(((url, date, resolution), response_time))
    if len(recent_data) < config.urls_limit:
        recent_data.extend(unrecent_data[: config.urls_limit - len(recent_data)])
    return recent_data[: config.urls_limit]


def getTotalUrls(data):
    """
    Get the total urls with filter by date and depulicate
    """
    total_urls = []
    if len(data) > config.urls_limit:
        total_urls = [url for (url, _, _), _ in filterByDate(data)]
    else:
        total_urls = [url for (url, _, _), _ in data]
    return list(dict.fromkeys(total_urls))


def is_ipv6(url):
    """
    Check if the url is ipv6
    """
    try:
        host = urllib.parse.urlparse(url).hostname
        ipaddress.IPv6Address(host)
        return True
    except ValueError:
        return False


def filterSortedDataByIPVType(sorted_data):
    """
    Filter sorted data by ipv type
    """
    ipv_type = getattr(config, "ipv_type", "ipv4")
    if ipv_type == "ipv4":
        return [
            ((url, date, resolution), response_time)
            for (url, date, resolution), response_time in sorted_data
            if not is_ipv6(url)
        ]
    elif ipv_type == "ipv6":
        return [
            ((url, date, resolution), response_time)
            for (url, date, resolution), response_time in sorted_data
            if is_ipv6(url)
        ]
    else:
        return sorted_data


def filterByIPVType(urls):
    """
    Filter by ipv type
    """
    ipv_type = getattr(config, "ipv_type", "ipv4")
    if ipv_type == "ipv4":
        return [url for url in urls if not is_ipv6(url)]
    elif ipv_type == "ipv6":
        return [url for url in urls if is_ipv6(url)]
    else:
        return urls
