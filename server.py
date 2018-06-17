import subprocess
import json
import requests
import time

import RPi.GPIO as GPIO
from flask import Flask, render_template, redirect, request
from celery import Celery

app = Flask(__name__)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379'
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])

globals = {
    'current_fan_speed' : 'off'
}

CONFIG = json.load(open('config.json'))

SOCKETS = {
    'etekcity0329-1':  {
        'on' : '176 528 208 528 192 528 560 176 192 528 192 528 192 544 208 528 192 544 192 544 192 528 560 176 208 528 560 160 192 544 560 176 192 544 192 528 560 176 560 176 192 544 192 544 560 176 560 176 192 5632',
        'off' : '176 560 176 544 176 560 560 160 176 560 160 560 160 576 176 544 176 544 192 560 160 544 576 160 176 544 544 176 176 560 560 160 176 560 176 560 560 160 544 176 528 240 512 176 176 576 176 544 160 5664'
    },
    'etekcity0329-3':  {
        'on' : '176 544 176 544 176 544 544 192 176 544 176 544 176 544 176 544 176 560 176 544 176 544 544 192 176 560 544 192 544 192 544 192 176 560 176 544 176 544 176 560 176 544 176 544 544 176 544 192 176 5648',
        'off' : '208 528 192 528 208 560 560 144 208 528 208 528 224 512 176 544 208 528 192 528 192 544 576 144 192 544 560 160 576 144 544 192 192 560 160 560 176 544 192 544 560 144 576 160 208 528 192 544 192 5632'
    },
    'etekcity0329-5':  {
        'on' : '176 544 192 528 176 560 560 176 208 528 256 480 192 544 208 528 208 528 192 544 592 144 592 144 208 512 592 144 192 544 560 176 192 560 128 576 176 544 192 560 176 560 160 544 544 176 592 144 192 5632',
        'off' : '176 560 176 544 176 544 560 176 176 544 176 544 176 544 192 544 192 544 176 544 544 176 560 208 144 544 544 176 192 560 544 176 176 544 192 544 176 544 176 544 544 192 544 192 176 560 176 544 176 5664'
    }
}

CEILING_FAN_PINS = {
    'light' : 18,
    'low' : 16,
    'med' : 22,
    'high' : 29,
    'off' : 12
}

OAUTH_REDIRECT_URL = '%s#access_token=%s&token_type=bearer&state=%s'

def switch_ceiling_fan(fan_mode):
    print "Toggling ceiling fan to %s" % fan_mode
    if fan_mode != 'light':
        globals['current_fan_speed'] = fan_mode

    pin = CEILING_FAN_PINS.get(fan_mode)
    GPIO.output(pin, 0)
    time.sleep(1)
    GPIO.output(pin, 1)

@celery.task
def switch_socket(socket, state):
    print "Switching socket %s to %s" % (socket, state)
    rc = subprocess.call(['sudo', 'pilight-send', '-p', 'raw', '-c', '"%s"' % SOCKETS[socket][state]])

def handle_execute_intent(request_id, intent):
    payload = intent.get('payload')
    commands = payload.get('commands')
    acted_upon_devices = []
    fan_mode = None
    for c in commands:
        devices = c.get('devices')
        executions = c.get('execution')
        for d in devices:
            for e in executions:
                device_id = d.get('id')
                command = e.get('command')
                if command == 'action.devices.commands.OnOff':
                    turn_on = e.get('params').get('on')
                    acted_upon_devices.append(device_id)
                    device_state = turn_on
                    if device_id == '401MHz-ceilingfan-bedroom-1357':
                        fan_mode = 'low' if turn_on else 'off'
                    elif device_id == '401MHz-ceiling-light-bedroom-1357':
                        fan_mode = 'light'
                elif command == "action.devices.commands.SetFanSpeed":
                    acted_upon_devices.append(device_id)
                    fan_mode = e.get('params').get('fanSpeed')

        for device_id in acted_upon_devices:
            if 'etekcity' in device_id:
                for i in xrange(0, 10):
                    switch_socket.delay(device_id, 'on' if device_state else 'off')
            elif '401MHz' in device_id:
                switch_ceiling_fan(fan_mode)
                device_state = False if globals['current_fan_speed'] == 'off' else 'true'

    r = render_template('execute.json',
        request_id=request_id,
        device_ids=json.dumps(acted_upon_devices),
        device_state=True if device_state else False,
        current_fan_speed=globals['current_fan_speed']))

    return r

def handle_query_intent(request_id, intent):
    print 'Got request ID %s' % request_id

    r = render_template('query.json',
        request_id=request_id,
        is_fan_on=False if globals['current_fan_speed'] == 'off' else 'true',
        current_fan_speed=globals['current_fan_speed'])

    print r

    return r

@app.route('/google-assistant/', methods=['POST'])
def google_assistant():
    body = request.json
    print body
    request_id = body.get('requestId')
    inputs = body.get('inputs')

    for ip in inputs:
        intent = ip.get('intent')
        if intent == 'action.devices.SYNC':
            return render_template('sync.json', request_id=request_id)
        elif intent == 'action.devices.QUERY':
            return handle_query_intent(request_id, ip)
        elif intent == 'action.devices.EXECUTE':
            return handle_execute_intent(request_id, ip)

@app.route('/resync')
def resync():
    url = 'https://homegraph.googleapis.com/v1/devices:requestSync'
    body = {
        'agent_user_id' : '1099'
    }
    params = {
        'key' : CONFIG['google']['resync_key']
    }
    r = requests.post(url, json=body, params=params)
    return r.text

@app.route('/livingroom/lights/<state>')
def sockets(state):
    if state not in ('on', 'off'):
        abort('404')

    i = 0
    while (i < 5):
        switch_socket(4, state)
        i+=1

    return 'Turned living room lights %s' % (state)

@app.route('/listonic')
def listonic():
    name = request.args.get('name')
    payload = {
        'listId': "12307143",
        'name': name,
        'CategoryId': 1
    }

    headers = {
         'Authorization' : 'Bearer %s'
    }

    r = requests.post('https://hl2api.listonic.com/api/lists/12307143/items',
                      headers=headers, json=payload)
    return r

@app.route('/auth')
def auth():
    client_id = request.args.get('client_id')
    redirect_uri = request.args.get('redirect_uri')
    state = request.args.get('state')
    response_type = request.args.get('response_type')

    access_token = CONFIG['google']['access_token']

    print redirect_uri

    redirect_url = OAUTH_REDIRECT_URL % (redirect_uri, access_token, state)
    return redirect(redirect_url, code=302)

def main():
    GPIO.setmode(GPIO.BOARD)
    for v in CEILING_FAN_PINS.values():
        GPIO.setup(v, GPIO.OUT, initial=1)

    app.run(port=80, debug=True)

if __name__ == '__main__':
    main()
