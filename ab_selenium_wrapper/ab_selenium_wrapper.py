import json
import os
import pickle
import random
import re
import time

import requests
from selenium import webdriver
from selenium.common import ElementClickInterceptedException, NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth

import ab_selenium_wrapper.proxy_extension_manager
from ab_selenium_wrapper.devices import devices


class WrappedWebElement:
    def __init__(self, element: WebElement, driver, timeout=10):
        self.element = element
        self.driver = driver
        self.timeout = timeout

    def click(self):
        try:
            self.element.click()
        except ElementClickInterceptedException:
            self.js_click()

    def js_click(self, xpath=None):
        target_element = self.element
        if xpath:
            target_element = self.find_element(By.XPATH, xpath).element

        self.driver.execute_script("arguments[0].click();", target_element)

    def wait_to_click(self, xpath=None):
        target_element = self.element
        if xpath:
            target_element = WebDriverWait(self.driver, self.timeout).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )

        try:
            target_element.click()
        except ElementClickInterceptedException:
            self.js_click(xpath)

    def type_text(self, text):
        self.element.clear()
        self.element.send_keys(text)

    def get_text(self):
        return self.element.text

    def is_displayed(self):
        return self.element.is_displayed()

    def is_enabled(self):
        return self.element.is_enabled()

    def find_element(self, by=By.XPATH, value=None):
        found_element = self.element.find_element(by, value)
        return WrappedWebElement(found_element, self.driver, self.timeout)

    def find_elements(self, by=By.XPATH, value=None):
        elements = self.element.find_elements(by, value)
        return [WrappedWebElement(el, self.driver, self.timeout) for el in elements]


def generate_device_configuration():
    device = random.choice(devices)
    device_metrics = device["deviceMetrics"]
    user_agent = device["userAgent"]

    chrome_options = {
        "deviceMetrics": {
            "width": device_metrics["width"],
            "height": device_metrics["height"],
            "pixelRatio": device_metrics["pixelRatio"]
        },
        "userAgent": user_agent
    }

    return chrome_options


class SeleniumWrapper:
    def __init__(self, timeout=10, speed=1, proxy=None, headless=False, mobile=False):
        chrome_options = Options()
        chrome_options.add_argument("--window-size=1920x1080")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--disable-infobars")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--disable-features=WebRTC")
        chrome_options.add_argument("--disable-features=IsolateOrigins,site-per-process")

        if mobile:
            device_config = generate_device_configuration()
            chrome_options.add_experimental_option("mobileEmulation", device_config)
            chrome_options.add_argument(f"user-agent={device_config['userAgent']}")

            if "iPhone" in device_config['userAgent']:
                chrome_options.add_argument(f"--sec-ch-ua-platform='iOS'")
                chrome_options.add_argument(f"--sec-ch-ua-mobile='?1'")
                chrome_options.add_argument(f"--sec-ch-ua-full-version='14.0'")
                webgl_vendor = "Apple Inc."
                renderer = "Apple A10 GPU"
            elif "Android" in device_config['userAgent']:
                chrome_options.add_argument(f"--sec-ch-ua-platform='Android'")
                chrome_options.add_argument(f"--sec-ch-ua-mobile='?1'")
                chrome_options.add_argument(
                    f"--sec-ch-ua-full-version='{device_config['userAgent'].split('Chrome/')[1].split(' ')[0]}'")
                webgl_vendor = "Qualcomm"
                renderer = "Adreno (TM) 630"
            else:
                chrome_options.add_argument(f"--sec-ch-ua-platform='Windows'")
                chrome_options.add_argument(f"--sec-ch-ua-mobile='?0'")
                webgl_vendor = "Intel Inc."
                renderer = "Intel Iris OpenGL Engine"

        if proxy is not None:
            print("Using proxy", proxy)
            proxy_user_pass, proxy_host_port = proxy.split('@')
            proxy_user, proxy_pass = proxy_user_pass.split(':')
            proxy_host, proxy_port = proxy_host_port.split(':')

            proxy_plugin_path = 'proxy_auth_plugin.zip'
            proxy_extension_manager.create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass,
                                                                proxy_plugin_path)
            chrome_options.add_extension(proxy_plugin_path)

        if headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")

        self.driver = webdriver.Chrome(options=chrome_options)

        if mobile:
            stealth(self.driver,
                    languages=["en-US", "en"],
                    vendor="Google Inc.",
                    platform=device_config["deviceMetrics"].get("platform", "Linux"),
                    webgl_vendor=webgl_vendor,
                    renderer=renderer,
                    fix_hairline=True)

        self.driver.set_page_load_timeout(60)

        self.timeout = timeout
        self.speed = speed

    def find_element_in_all_frames(self, by, value):
        try:
            return self.driver.find_element(by, value)
        except (NoSuchElementException, TimeoutException):
            pass

        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

        for iframe in iframes:
            self.driver.switch_to.frame(iframe)
            try:
                element = self.find_element_in_all_frames(by, value)
                if element:
                    return element
            except (NoSuchElementException, TimeoutException):
                pass
            self.driver.switch_to.default_content()

        raise NoSuchElementException(f"Element not found with {by} = {value}")

    def find_elements_in_all_frames(self, by, value):
        elements = []
        try:
            elements.extend(self.driver.find_elements(by, value))
        except (NoSuchElementException, TimeoutException):
            pass

        iframes = self.driver.find_elements(By.TAG_NAME, "iframe")

        for iframe in iframes:
            self.driver.switch_to.frame(iframe)
            try:
                elements.extend(self.find_elements_in_all_frames(by, value))
            except (NoSuchElementException, TimeoutException):
                pass
            self.driver.switch_to.default_content()

        return elements

    def get_number_of_children(self, xpath):
        try:
            parent_element = self.find_element_in_all_frames(By.XPATH, xpath)
            children = parent_element.find_elements(By.XPATH, "./*")
            return len(children)
        except NoSuchElementException:
            print(f"Error: Element with xpath {xpath} not found.")
            return 0

    def get_element(self, xpath) -> WebElement:
        return WebDriverWait(self.driver, self.timeout).until(
            lambda driver: self.find_element_in_all_frames(By.XPATH, xpath)
        )

    def count_elements(self, xpath):
        return len(self.driver.find_elements(By.XPATH, xpath))

    def js_click(self, xpath):
        element = WebDriverWait(self.driver, self.timeout).until(
            lambda driver: self.find_element_in_all_frames(By.XPATH, xpath)
        )
        self.driver.execute_script("arguments[0].click();", element)

    def wait_to_click(self, xpath, timeout=None, optional=False):
        timeout = timeout or self.timeout
        try:
            element = WebDriverWait(self.driver, timeout).until(
                lambda driver: self.find_element_in_all_frames(By.XPATH, xpath)
            )
            element.click()
        except TimeoutException:
            if optional:
                return
            print(f"Error: optional element with xpath {xpath} not found.")
            return
        except ElementClickInterceptedException:
            self.js_click(xpath)

        time.sleep(self.speed)

    def click_anything_that_says(self, text, timeout=None, optional=False):
        xpath = f"//*[translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')='{text.lower()}']"
        return self.wait_to_click(xpath, timeout, optional)

    def element_contains_text_exists(self, text, timeout=10):
        xpath = f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            return True
        except (NoSuchElementException, TimeoutException):
            return False

    def type_text(self, xpath, text):
        input_element = WebDriverWait(self.driver, self.timeout).until(
            EC.visibility_of_element_located((By.XPATH, xpath))
        )
        input_element.clear()
        for characer in text:
            input_element.send_keys(characer)
            time.sleep(self.speed / 10 * random.uniform(0.5, 2))
        time.sleep(self.speed)

    def select_random_option(self, xpath):
        select_element = Select(WebDriverWait(self.driver, self.timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ))
        select_element.select_by_index(random.randint(0, len(select_element.options) - 1))
        time.sleep(self.speed)

    def select_specific_option(self, xpath, option_text):
        select_element = Select(WebDriverWait(self.driver, self.timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ))
        select_element.select_by_visible_text(option_text)
        time.sleep(self.speed)

    def wait_to_appear(self, xpath, timeout=60):
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(
                    (By.XPATH,
                     xpath)
                )
            )
        except TimeoutException:
            print("Error: Element not found.")
            return False
        return True

    def save_image_by_xpath(self, xpath, destination_folder, file_name):
        try:
            image_element = self.find_element_in_all_frames(By.XPATH, xpath)
            image_url = image_element.get_attribute('src')
            response = requests.get(image_url)

            if response.status_code == 200:
                if not os.path.exists(destination_folder):
                    os.makedirs(destination_folder)

                file_path = os.path.join(destination_folder, file_name)

                with open(file_path, 'wb') as file:
                    file.write(response.content)

                print(f"Image successfully saved to: {file_path}")
            else:
                print(f"Error downloading image. Status code: {response.status_code}")

        except Exception as e:
            print(f"An error occurred while trying to save the image: {str(e)}")

    def exists(self, xpath, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath)))
            return True
        except (NoSuchElementException, TimeoutException):
            return False

    def exists_cookies(self, name):
        domain = self.driver.current_url.split("//")[-1].split("/")[0]
        folder_path = os.path.join("./cookies/", domain)
        file_path = os.path.join(folder_path, f'{name}.json')
        return os.path.exists(file_path)

    def save_cookies(self, name):
        domain = self.driver.current_url.split("//")[-1].split("/")[0]
        folder_path = os.path.join("./cookies/", domain)
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        file_path = os.path.join(folder_path, f'{name}.json')
        with open(file_path, 'w') as file:
            json.dump(self.driver.get_cookies(), file)
        print(f"Cookies saved to {file_path}")

    def load_cookies(self, name):
        domain = self.driver.current_url.split("//")[-1].split("/")[0]
        folder_path = os.path.join("./cookies/", domain)
        file_path = os.path.join(folder_path, f'{name}.json')
        if os.path.exists(file_path):
            with open(file_path, 'r') as file:
                cookies = json.load(file)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)
            print(f"Cookies loaded from {file_path}")
        else:
            print(f"No cookies found at {file_path}")

    def load_cookies_from_file(self, path):
        domain = self.driver.current_url.split("//")[-1].split("/")[0]
        folder_path = os.path.join("./cookies/", domain)
        file_path = os.path.join(folder_path, path)


        if not os.path.exists(file_path):
            print(f"No cookies found at {file_path}")
            return

        try:
            # Detectar el formato según la extensión
            if path.endswith('.json'):
                with open(file_path, 'r') as file:
                    cookies = json.load(file)
            elif path.endswith('.pkl'):
                with open(file_path, 'rb') as file:
                    cookies = pickle.load(file)
            else:
                print(f"Error: Format not supported {path}. Allowed formats are '.json' and '.pkl'.")
                return

            # Añadir cada cookie al navegador
            for cookie in cookies:
                # Ajustar el campo 'expiry' si es necesario
                if 'expiry' in cookie:
                    cookie['expiry'] = int(cookie['expiry'])
                self.driver.add_cookie(cookie)

            print(f"Cookies loaded from {file_path}")

        except Exception as e:
            print(f"An error occurred while loading cookies: {str(e)}")

    def upload_image(self, file_input_xpath, image_path):
        file_input = self.find_element_in_all_frames(By.XPATH, file_input_xpath)
        file_input.send_keys(image_path)

    def focus_element(self, xpath):
        try:
            element = self.find_element_in_all_frames(By.XPATH, xpath)
            self.driver.execute_script("arguments[0].focus();", element)
            print(f"Focus applied to element with xpath: {xpath}")
        except (NoSuchElementException, TimeoutException):
            print(f"Error: Element with xpath {xpath} not found.")

    def write_text_via_js(self, xpath, text):
        try:
            element = self.find_element_in_all_frames(By.XPATH, xpath)

            self.driver.execute_script("arguments[0].value = arguments[1];", element, text)

            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)

        except (NoSuchElementException, TimeoutException) as e:
            print(f"Error: Element with xpath {xpath} not found. Exception: {str(e)}")

    def wait_for_first_occurrence(self, text_list, timeout=10):
        lower_text_list = [text.lower() for text in text_list]
        xpath_list = [
            f"//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')]"
            for text in lower_text_list]
        start_time = time.time()
        while time.time() - start_time < timeout:
            for index, xpath in enumerate(xpath_list):
                if self.exists(xpath, timeout=1):
                    return index
            time.sleep(0.5)
        raise TimeoutException(f"None of the texts {text_list} appeared in the specified timeout.")

    def wait_for_url_change_and_match(self, regex_pattern, timeout=10):
        end_time = time.time() + timeout

        while time.time() < end_time:
            current_url = self.driver.current_url
            if re.match(regex_pattern, current_url):
                return True

            time.sleep(0.5)

        return False