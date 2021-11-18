#!/usr/bin/env python
# -- coding: utf-8 --

import glob
import requests
import socket
import subprocess
from urllib.parse import urlparse

path = "/etc/systemd/system/celery"  #change directory path #/etc/systemd/system/celery
serviceFiles = glob.glob(path+"*.service")

def get_queue_names(service_files):
    queues = []
    for fl in service_files:
        file = open(fl, 'r')
        content = file.readlines()
        if content:
            for line in content:
                if line.startswith("ExecStart"):
                    if (line.find('-Q') > 0):
                        queue_name = line.split('-Q')[1].split()[0]
                        servicePath = fl.split("/")
                        serviceName = servicePath[-1]
                        queues.append(queue_name+","+serviceName)
                        #print(fl + "  -  " + queue_name)
    return queues


def get_server_info():
    server = open("/etc/conf.d/dopigo",'r') #change directory path #/etc/conf.d/dopigo
    info = server.readlines()
    url = ""
    for line in info:
        if(line.startswith("DOPIGO_BROKER_URL")):
            url = line.split('=')[1]
    url = url.replace("amqp", "http").replace("5672","15672").replace("\n", "")
    urlCopy = url.split("//")
    url = urlCopy[0]+"//"+urlCopy[1]+"/"+urlCopy[2]
    return url


def get_consumer_queues(server_url,ips):
    server_url = server_url+"api/consumers"
    response = requests.get(server_url)  ###UNCOMMENT LATER
    #response = requests.get("http://guest:guest@localhost:15672/api/consumers")
    result = response.json()
    if response.status_code > 300:
        raise ValueError("Queue listesi alınamadı: {}".format(server_url))
    else:
        print("Connected to "+server_url)
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
    if(external.status_code > 300):
        raise ConnectionError("Could not connect to https://api.ipify.org")
    else: external = external.text
    s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    s.connect((hostname,80)) ##UNCOMMENT LATER
    #s.connect(("8.8.8.8", 80))
    local = s.getsockname()[0]
    ips = [external,local]
    print("IP Adresses: ")
    print(ips)
    print("")
    s.close()
    return ips

def check_queues():
    services_and_queues = get_queue_names(serviceFiles)
    service_queues = []
    service_names = []
    for sr in services_and_queues:
        names = sr.split(",")
        service_queues.append(names[0])
        service_names.append(names[1])
    url = get_server_info()
    hostname = urlparse(url).hostname
    queues_running = get_consumer_queues(url,get_ip_addresses(hostname))
    print("Queues from the services: ")
    print(service_queues)
    print(service_names)
    print("Queues running: ")
    print(queues_running)
    queues_not_found = []
    result = True
    i = 0;
    for q in service_queues:
        if not(q in queues_running):
            print("Queue: "+q+" was not found")
            queues_not_found.append(service_names[i])
            result = False
        else:
            print("Queue: "+q+" was found")
        i+=1
    if(result):
        print("Success! Everything's working successfully")
    else:
        print("Error! There are services that need to restart")
    print("Services that need to restart ")
    print(queues_not_found)
    return queues_not_found

def restart_services(services):
    for service in services:
        result = subprocess.run(["systemctl","start",service])
        if(not result.check_returncode()):
            msg = service + " is restarted."
            print(msg)
            send_slack_message(msg)
        else:
            msg = service + " service needs to be restarted but did not restart."
            print(msg)
            send_slack_message(msg)


def send_slack_message(message):
    jsondata = '{"text": "Celery Worker Monitor: %s"}' % message
    response = requests.post("https://hooks.slack.com/services/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", #CHANGE URL
                             data=jsondata)
    if(response.status_code > 300):
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )
    else:
        print(response.status_code)


try:
    restart_services(check_queues())
except Exception as e:
    msg = "An error occurred: {}".format(e)
    print(msg)
    send_slack_message(msg)