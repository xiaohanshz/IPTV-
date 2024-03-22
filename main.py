import config
import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium_stealth import stealth
from bs4 import BeautifulSoup
from utils import (
    getChannelItems,
    updateChannelUrlsM3U,
    updateFile,
    getUrlInfo,
    compareSpeedAndResolution,
    getTotalUrls,
    filterSortedDataByIPVType,
    filterByIPVType,
)
import logging

logging.basicConfig(
    filename="result_new.log",
    filemode="a",
    format="%(message)s",
    level=logging.INFO,
)

class UpdateSource:

    def setup_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("start-maximized")
        options.add_argument("--headless")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("blink-settings=imagesEnabled=false")
        driver = webdriver.Chrome(options=options)
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        return driver

    async def visit_page(self, name, is_favorite):
        channel_urls = {}
        page_num = config.favorite_page_num if is_favorite else config.default_page_num
        for page in range(1, page_num):
            try:
                page_url = f"https://www.foodieguide.com/iptvsearch/?page={page}&s={name}"
                self.driver.get(page_url)
                await self.driver_wait(name)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                tables_div = soup.find("div", class_="tables")
                results = tables_div.find_all("div", class_="result") if tables_div else []
                if not any(result.find("div", class_="m3u8") for result in results):
                    break
                info_list = []
                for result in results:
                    try:
                        url, date, resolution = getUrlInfo(result)
                        if url:
                            info_list.append((url, date, resolution))
                    except Exception as e:
                        logging.error(f"Error on result {result}: {e}")
                        continue
                sorted_data = await compareSpeedAndResolution(info_list)
                ipv_sorted_data = filterSortedDataByIPVType(sorted_data)
                if ipv_sorted_data:
                    channel_urls[name] = getTotalUrls(ipv_sorted_data)
                    for (url, date, resolution), response_time in ipv_sorted_data:
                        logging.info(
                            f"Name: {name}, URL: {url}, Date: {date}, Resolution: {resolution}, Response Time: {response_time}ms"
                        )
                else:
                    channel_urls[name] = filterByIPVType(channelObj[name])
            except Exception as e:
                logging.error(f"Error on page {page}: {e}")
                continue
        return channel_urls

    async def driver_wait(self, name):
        await WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.tables"))
        )

    async def process_channels(self):
        tasks = []
        for cate, channel_obj in getChannelItems().items():
            for name in channel_obj.keys():
                is_favorite = name in config.favorite_list
                tasks.append(self.visit_page(name, is_favorite))
        return await asyncio.gather(*tasks)

    def main(self):
        self.driver = self.setup_driver()
        asyncio.run(self.process_channels())
        updateFile(config.final_file, "live_new.m3u")
        updateFile("result.log", "result_new.log")

UpdateSource().main()
