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

    def __init__(self):
        self.driver = self.setup_driver()

    async def visit_page(self, cate, name, is_favorite):
        channelUrls = {}
        try:
            for page in range(1, config.favorite_page_num if is_favorite else config.default_page_num):
                page_url = f"http://tonkiang.us/?page={page}&s={name}"
                self.driver.get(page_url)
                await self.driver_wait_for_element(By.CSS_SELECTOR, "div.tables")

                soup = BeautifulSoup(self.driver.page_source, "html.parser")
                tables_div = soup.find("div", class_="tables")
                results = tables_div.find_all("div", class_="result") if tables_div else []
                if not any(result.find("div", class_="m3u8") for result in results):
                    break
                infoList = []
                for result in results:
                    try:
                        url, date, resolution = getUrlInfo(result)
                        if url:
                            infoList.append((url, date, resolution))
                    except Exception as e:
                        logging.error(f"Error on result {result}: {e}")
                        continue
                sorted_data = await compareSpeedAndResolution(infoList)
                ipvSortedData = filterSortedDataByIPVType(sorted_data)
                if ipvSortedData:
                    channelUrls[name] = getTotalUrls(ipvSortedData) or channelUrls[name]
                    for (url, date, resolution), response_time in ipvSortedData:
                        logging.info(
                            f"Name: {name}, URL: {url}, Date: {date}, Resolution: {resolution}, Response Time: {response_time}ms"
                        )
                else:
                    channelUrls[name] = filterByIPVType(channelUrls[name])
        except Exception as e:
            logging.error(f"Error on category {cate} and name {name}: {e}")
        updateChannelUrlsM3U(cate, channelUrls)
        return cate, channelUrls

    async def driver_wait_for_element(self, by, value, timeout=10):
        try:
            await WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
        except Exception as e:
            logging.error(f"Error waiting for element: {e}")

    async def process_channels(self):
        tasks = []
        for cate, channelObj in getChannelItems().items():
            for name in channelObj.keys():
                is_favorite = name in config.favorite_list
                tasks.append(self.visit_page(cate, name, is_favorite))
        return await asyncio.gather(*tasks)

    def main(self):
        self.driver = self.setup_driver()  # 创建Chrome Driver实例
        asyncio.run(self.process_channels())
        updateFile(config.final_file, "live_new.m3u")
        updateFile("result.log", "result_new.log")


UpdateSource().main()
