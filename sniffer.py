"""
replay.py
Replay the output of pilight-debug to allow you to easily spot
correct RF codes among the noise.

"""

import argparse
import subprocess
import time

def replay(filename):
    with open(filename) as f:
        next_line_code = False
        for line in f.readlines():
            if line.startswith('Raw code:'):
                next_line_code = True
            elif next_line_code:
                next_line_code = False

                #if len(line) != 202:
                #    continue

                print line
                rc = subprocess.call(['sudo', 'pilight-send', '-p', 'raw', '-c', '"%s"' % line])
                time.sleep(1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('filename', help='Output of pilight-debug to replay')
    args = parser.parse_args()
    replay(args.filename)
