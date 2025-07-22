#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os
import io
picdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'pic')
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)

import base64
import logging
import sched
import requests
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

def load_images(access_key, collection_id):
    try:
        res = requests.get(API_URL + "/images/getDitheredImagesByCollection/" + str(collection_id),
                        headers={
                                "Authorization": f"Bearer {access_key}",
                                "Accept": "application/json"
                            })
        if res.status_code == 200:
            data_json = res.json()
            for image_id in data_json:
                image_bytes = data_json[image_id]["data"]
                image_stream = io.BytesIO(base64.b64decode(image_bytes.encode("utf-8")))
                im = Image.open(image_stream)
                im.save(f'{picdir}/{image_id}.bmp', format="BMP")
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
    Himage = Image.open(os.path.join(picdir, images[counter.value()%len(images)]))
    epd.display(epd.getbuffer(Himage))

def schedule_intervaled_task(scheduler, interval, action, args=()):
    scheduler.enter(interval, 1, schedule_intervaled_task,
                    (scheduler, interval, action, args))
    action(*args)

def get_display_config(access_key):
    serial_number = get_raspberry_pi_serial()
    if serial_number == "0000000000000000":
        raise Exception("No serial number found")
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

def start_display(access_key, collection_id):
    scheduler = sched.scheduler()
    counter = Counter()
    schedule_intervaled_task(scheduler, 60*60, load_images, (access_key, collection_id))
    schedule_intervaled_task(scheduler, 60*20, rotate_image, (counter,))
    scheduler.run()

def get_collections(access_key, device_model):
    try:
        res = requests.get(API_URL + "/images/getCollections/" + str(device_model),
                        headers={
                                "Authorization": f"Bearer {access_key}",
                                "Accept": "application/json"
                            })
        if res.status_code == 200:
            return res.json()
        else:
            logging.info(res.reason)
    except Exception as e:
        logging.info(f'Error loading collections: {e}')

def prompt_device_config(access_key):
    print("Creating config for device")
    name = input("Device config name: ")
    collections = get_collections(access_key)
    print("Collections")
    print(collections)
    for i, collection in enumerate(collections):
        print(f'{i}: {collection["name"]}')
    collection_id = input("Select input here:")

def main(epd):
    json_keys = prompt_login()
    access_key = json_keys["access"]
    refresh_token = json_keys["refresh"]
    config = get_display_config(access_key)
    #TODO: validate config
    if config:
        logging.info("init and Clear")
        epd.init()
        epd.Clear()
        start_display(access_key, int(config["collection"]))
    elif config == {}:
        prompt_device_config(access_key, DEVICE_MODEL)
    else:
        #TODO: ask to configure device here
        logging.info("No config found")
        raise Exception("Server error fetching config.")


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