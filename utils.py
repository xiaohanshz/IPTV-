import aiohttp
import asyncio
import config
import time
import re
import datetime
import os
import urllib.parse
import ipaddress
import subprocess


async def play_url(url):
    """
    Test playback of a live stream URL for the specified duration.
    """
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
    Filter URLs based on playback smoothness.
    """
    valid_urls = []
    for url in url_list:
        if await play_url(url):
            valid_urls.append(url)
            # If the URL plays smoothly, write it to the M3U file
            updateChannelUrlsM3U("cate", {name: [url]})  # Assuming "cate" is the category
        if len(valid_urls) >= config.urls_limit:
            break
    return valid_urls


async def getChannelItems():
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


async def process_channels():
    """
    Process channels to filter URLs based on playback smoothness.
    """
    tasks = []
    channel_items = await getChannelItems()
    for cate, channelObj in channel_items.items():
        for name, urls in channelObj.items():
            tasks.append(filterByPlayback(urls))
    filtered_urls = await asyncio.gather(*tasks)
    channel_urls = {}
    for (cate, channelObj), urls in zip(channel_items.items(), filtered_urls):
        channel_urls[cate] = {name: urls for name, _ in channelObj.items()}
    return channel_urls


def main():
    """
    Main function to process channels and update files.
    """
    loop = asyncio.get_event_loop()
    channel_urls = loop.run_until_complete(process_channels())
    updateChannelUrlsM3U("cate", channel_urls)
    updateFile(config.final_file, "live_new.m3u")


if __name__ == "__main__":
    main()
