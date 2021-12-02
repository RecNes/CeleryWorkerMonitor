#!/usr/bin/env python3
# -- coding: utf-8 --

import glob
import json
import requests
import argparse
import socket
import logging
import subprocess
from urllib.parse import urlparse

parser = argparse.ArgumentParser()

parser.add_argument(
    "-l",
    "--log-level",
    default="error",
    help=(
        "Provide logging level. "
        "Example --log-level=debug. Default value is set to warning.",
    ),
)

arguments = parser.parse_args()

levels = {
    'critical': logging.CRITICAL,
    'error': logging.ERROR,
    'warning': logging.WARNING,
    'info': logging.INFO,
    'debug': logging.DEBUG,
}

level = levels.get(arguments.log_level.lower())

if level is None:
    raise ValueError(
        f"Inappropriate value for --log-level: {arguments.log_level}"
        f" -- must be one of: {' | '.join(levels.keys())}"
    )

logging.basicConfig(filename="/var/log/celery_worker_monitor.log",filemode="a", format="%(asctime)s - %(message)s", level=level)

path = "/etc/systemd/system/celery"  #change directory path #/etc/systemd/system/celery
service_files = glob.glob(path + "*.service")

def get_queue_names(service_files):
    queues = []
    for service_file in service_files:
        try:
            with open(service_file, 'r') as file:
                content = file.readlines()
                if content:
                    for line in content:
                        flag = False
                        if line.startswith("ExecStart"):
                            if (line.find('-Q') > 0):
                                logging.debug(f"For {service_file}: ")
                                queue_name = line.split('-Q')[1].split()[0]
                                logging.debug(f"queue_name => {queue_name}")
                                service_path = service_file.split("/")
                                logging.debug(f"service_path => {service_path}")
                                service_name = service_path[-1]
                                logging.debug(f"service_name => {service_name}")
                                queues.append(f"{queue_name},{service_name}")
                                
                                flag = True
                                break
                    # if ExecStart is not found, log to the file
                    if not flag:
                        logging.error(f"ExecStart could not found in {service_file}.")
        except Exception:
            logging.exception(f"{service_file} could not opened.")            

    return queues


def get_server_info():
    try:
        flag = False
        with open("/etc/conf.d/dopigo", 'r') as server:
            info = server.readlines()
            url = ""
            for line in info:
                if(line.startswith("DOPIGO_BROKER_URL")):
                    url = line.split('=')[1]
                    flag = True
                    break
        
            # if DOPIGO_BROKER_URL is not found
            if not flag:
                logging.warning("Could not find DOPIGO_BROKER_URL in /etc/conf.d/dopigo")

            url = url.replace("amqp", "http").replace("5672","15672").replace("\n", "")
            urlCopy = url.split("//")
            url = f"{urlCopy[0]}//{urlCopy[1]}/{urlCopy[2]}"

            return url
    except Exception:
        message = "/etc/conf.d/dopigo could not opened."
        logging.exception(message)
        raise IOError(message)


def get_consumer_queues(server_url, ips):
    server_url = f"{server_url}api/consumers"
    response = requests.get(server_url)
    result = response.json()
    if response.status_code > 300:
        message = f"Queue listesi alınamadı: {server_url}"
        logging.error(message)
        raise ValueError(message)
    
    message = f"Connected to {server_url}"
    logging.debug(message)
    print(message)
    queues = []
    for i in result:
        print(i["channel_details"]["peer_host"] + "  -  " + i["queue"]["name"])
        ip = i["channel_details"]["peer_host"]
        if(ip in ips):
            queues.append(i["queue"]["name"])
    print("")
    return queues


def get_ip_addresses(hostname):
    external = requests.get("https://api.ipify.org")
    logging.debug("Connecting to ipify...")
    if external.status_code > 300:
        message = "Could not connect to https://api.ipify.org"
        logging.error(message)
        raise ConnectionError(message)
    else:
        external = external.text
    
    logging.debug(f"Connected to {external} on {80}")
    logging.debug(f"hostname is {hostname}")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((hostname, 80))
    local = s.getsockname()[0]
    ips = [external, local]
    print(f"IP Addresses:\n{ips}")
    s.close()
    return ips


def check_queues():
    services_and_queues = get_queue_names(service_files)
    service_queues = []
    service_names = []
    for service_and_queue in services_and_queues:
        names = service_and_queue.split(",")
        service_queues.append(names[0])
        service_names.append(names[1])

    logging.debug(f"Queues are retrieved: {service_queues}")
    logging.debug(f"Services are retrieved: {service_names}")

    url = get_server_info()
    hostname = urlparse(url).hostname
    running_queues = get_consumer_queues(url, get_ip_addresses(hostname))
    print(f"Queues from the services:\n{service_queues}\n{service_names}")

    print(f"Running queues:\n{running_queues}")

    logging.debug(f"Running queues: {running_queues}")

    queues_not_found = []
    result = True

    for queue, index in enumerate(service_queues):
        if queue not in running_queues:
            message = f"Queue {queue} was not found!"
            logging.warning(message)
            print(message)

            queues_not_found.append(service_names[index])
            result = False
        else:
            message = f"Queue {queue} was found."
            logging.debug(message)
            print(message)

    if result:
        message = "Success! Everything's working successfully"
        logging.debug(message)
        print(message)
    else:
        message = "There are services that need to restart"
        logging.error(message)
        print(message)

    log_message = f"Services that need to restart {queues_not_found}"
    logging.error(log_message)
    print(log_message)

    return queues_not_found


def restart_services(services):
    for service in services:
        message = ""
        result = subprocess.run(["systemctl","start",service])
        logging.debug("Trying to start " + service)
        if not result.check_returncode():
            message = f"{service} is restarted."
            logging.debug(message)
            print(message)
        else:
            message =  f"{service} service needs to be restarted but did not restart."
            logging.error(message)
            print(message)
        
        # send_slack_message(message)


def send_slack_message(message):
    data = {}
    data["text"] = f"Celery Worker Monitor: {message}"
    json_data = json.dumps(data)
    response = requests.post("https://hooks.slack.com/services/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", #CHANGE URL
                             data=json_data)
    if response.status_code > 300:
        error_message = f"Request to Slack returned an error {response.status_code}, the response is:\n{response.text}"
        logging.error(error_message)
        raise ValueError(error_message)
    else:
        print(f"Returned response's status code is {response.status_code}")


def main():
    try:
        restart_services(check_queues())
    except Exception as e:
        msg = "An error occurred: {}".format(e)
        print(msg)
        # send_slack_message(msg)


if __name__ == '__main__':
    main()
    