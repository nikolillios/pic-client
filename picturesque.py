#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import io
picdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'pic')
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)
os.makedirs(picdir, exist_ok=True)

import base64
import logging
import sched
import requests
import json
from waveshare_epd import epd7in3e
import time
from PIL import Image,ImageDraw,ImageFont
import traceback

logging.basicConfig(level=logging.DEBUG)

API_URL = "http://192.168.12.214:8000"
DEVICE_MODEL = 1 #TODO: input from startup script

def prompt_login():
    # Return access key and refresk token
    while True:
        # username = input("Enter username:\n")
        # password = input ("Enter password:\n")
        username = "nikolillios"
        password = "niko1234"
        res = requests.post(API_URL + "/token/", {
            "username": username,
            "password": password
        })
        try:
            data = res.json()
            return data
        except Exception as e:
            logging.info(e)

def save_tokens(token_data, filename = 'tokens.json') -> None:
    """Save tokens to file"""
    try:
        with open(filename, 'w') as f:
            json.dump(token_data, f, indent=2)
        print(f"Tokens saved to {filename}")
    except IOError as e:
        print(f"Error saving tokens: {e}")

def load_tokens(filename = 'tokens.json'):
    """Load tokens from file"""
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error loading tokens: {e}")
        return None

def refresh_access_token():
    json_tokens = load_tokens()
    if not json_tokens:
        raise Exception("No tokens to refresh with")
    res = requests.post(API_URL + "/token/refresh/", {
        "refresh": json_tokens["refresh"]
    })
    if res.status_code == 200:
        logging.info("Refreshed access tokens")
        save_tokens(res.json())
    else:
        logging.error(res.reason)
        return None

def refresh_with_retry():
    refreshed_tokens = False
    while not refreshed_tokens:
        refreshed = refresh_access_token()

def get_raspberry_pi_serial():
    """
    Extracts the serial number from the /proc/cpuinfo file on a Raspberry Pi.
    """
    cpuserial = "0000000000000000"  # Default value if serial not found or error occurs
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    cpuserial = line[10:26]  # Extract the 16-character serial number
                    break  # Exit loop once serial is found
    except FileNotFoundError:
        cpuserial = "ERROR: /proc/cpuinfo not found"
    except Exception as e:
        cpuserial = f"ERROR: {e}"
    return cpuserial

def get_auth_headers(access_key):
    return {
        "Authorization": f"Bearer {access_key}",
        "Accept": "application/json"
    }

def prune_stale_images(stale_images):
    for filename in stale_images:
        file_path = os.path.join(picdir, filename)
        if os.path.isfile(file_path) or os.path.islink(file_path):
            os.remove(file_path)

def load_images():
    access_key = load_tokens()["access"]
    config = get_display_config(access_key, get_raspberry_pi_serial())
    logging.info("Got config")
    logging.info(config)
    if not config:
        logging.error("No config found when loading images")
        return
    try:
        res = requests.get(API_URL + "/images/getDitheredImagesByCollection/" + str(config["collection"]),
                        headers={
                                "Authorization": f"Bearer {access_key}",
                                "Accept": "application/json"
                            })
        if res.status_code == 200:
            data_json = res.json()
            image_ids = [image for image in data_json]
            prunable_images = [file for file in os.listdir(picdir) if file.split(".")[0] not in image_ids]
            prune_stale_images(prunable_images)
            for image_id in data_json:
                if image_id in os.listdir(picdir):
                    continue
                image_bytes = data_json[image_id]["data"]
                image_stream = io.BytesIO(base64.b64decode(image_bytes.encode("utf-8")))
                im = Image.open(image_stream)
                im.save(f'{picdir}/{image_id}.bmp', format="BMP")
        elif res.status_code == 401:
            refresh_with_retry()
            load_images()
        else:
            logging.info(res.reason)
    except Exception as e:
        logging.info(f'Error loading images: {e}')

class Counter():
    def __init__(self, start=0):
        self._val = start
    
    def add(self, inc=1):
        self._val += inc

    def value(self):
        return self._val

def rotate_image(counter):
    images = os.listdir(picdir)
    counter.add()
    if not images:
        logging.info("No images to display")
        return
    Himage = Image.open(os.path.join(picdir, images[counter.value()%len(images)]))
    epd.display(epd.getbuffer(Himage))

def schedule_intervaled_task(scheduler, interval, action, args=()):
    scheduler.enter(interval, 1, schedule_intervaled_task,
                    (scheduler, interval, action, args))
    action(*args)

def get_display_config(access_key, serial_number):
    res = requests.get(API_URL + "/images/getConfigForDevice/" + serial_number,
                       headers={
                            "Authorization": f"Bearer {access_key}",
                            "Accept": "application/json"
                        })
    if res.status_code == 200:
        return res.json()
    elif res.status_code == 204:
        logging.info(f'No Config found for serial: {serial_number}')
        return {}
    else:
        logging.info(res.reason)
        return None

def start_display():
    scheduler = sched.scheduler()
    counter = Counter()
    schedule_intervaled_task(scheduler, 60*1, load_images)
    schedule_intervaled_task(scheduler, 60*1, rotate_image, (counter,))
    scheduler.run()

def get_collections(access_key):
    res = requests.get(API_URL + "/images/getCollections/" + str(DEVICE_MODEL),
                    headers={
                            "Authorization": f"Bearer {access_key}",
                            "Accept": "application/json"
                        })
    if res.status_code == 200:
        return res.json()
    elif res.status_code == 401:
        refresh_access_token()
    else:
        logging.info(res.reason)

def prompt_device_config(serial_number, collections):
    access_key = load_tokens()["access"]
    print("Creating config for device")
    name = input("Device config name: ")
    valid_collection_selected = False
    while not valid_collection_selected:
        if not collections:
            continue
        for i, collection in enumerate(collections):
            print(f'{i}: {collection["name"]}')
        n_cols = len(collections)
        print(f'{n_cols}: Reload Collections')
        collection_idx = int(input("Select input here:"))
        if collection_idx == n_cols:
            logging.info("Reloading collections...")
            continue
        elif collection_idx in range(n_cols):
            valid_collection_selected = True
    body = {
        "device_name": name,
        "serial":  serial_number,
        "device_model": DEVICE_MODEL,
        "collection_id": str(collections[collection_idx]["id"])
    }
    res = requests.post(API_URL + "/images/createConfigForDevice/", body,
                        headers={
                            "Authorization": f"Bearer {access_key}",
                            "Accept": "application/json"
                        })
    if res.status_code == 200:
        logging.info("Successfully created new device config!")
        return res.json()
    else:
        logging.info(f'Error while creating config: {res.reason}')


def main(epd):
    if load_tokens() and refresh_access_token():
        logging.info("Refresh token valid")
    else:
        keys = prompt_login()
        save_tokens(keys)
    json_keys = load_tokens()
    access_key = json_keys["access"]
    refresh_token = json_keys["refresh"]
    serial_number = get_raspberry_pi_serial()
    if serial_number == "0000000000000000":
        raise Exception("No serial number found")
    config = get_display_config(access_key, serial_number)
    #TODO: validate config
    collections = None
    while not collections:
        collections = get_collections(access_key)
    while not config:
        if config == {}:
            logging.info("No config found")
            try:
                config = prompt_device_config(serial_number, collections)
            except Exception as e:
                logging.error(e)
        else:
            raise Exception("Server error fetching config.")
    logging.info("init and Clear")
    epd.init()
    epd.Clear()
    start_display()


epd = epd7in3e.EPD()
while True:
    try:
        main(epd)
    except IOError as e:
        logging.info(e)
    except KeyboardInterrupt:
        logging.info("ctrl + c:")
        epd7in3e.epdconfig.module_exit(cleanup=True)
        exit()
    except Exception as e:
        logging.error(f'Unexpected error encountered: {e}')
        traceback.print_exc()
