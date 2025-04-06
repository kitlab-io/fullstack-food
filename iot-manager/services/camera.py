import subprocess
import pathlib
from datetime import datetime, timezone
# v4l2-ctl list devices
# Output: cedrus (platform:cedrus):
# 	/dev/video0
# 	/dev/media0

# USB Cam: USB Cam (usb-5200000.usb-1.2):
# 	/dev/video1
# 	/dev/video2
# 	/dev/media1

# ffmpeg list formats
# [video4linux2,v4l2 @ 0xaaaab2fa08c0] Compressed:       mjpeg :          Motion-JPEG : 640x480 320x240 352x288 640x480 800x600 1280x720 1920x1080 1600x1200 2048x1536 2592x1944
# [video4linux2,v4l2 @ 0xaaaab2fa08c0] Raw       :     yuyv422 :           YUYV 4:2:2 : 640x480 320x240 352x288 640x480 800x600 1280x720 1920x1080 1600x1200 2048x1536 2592x1944

path_store_photos = pathlib.Path('photos')

class Camera:
    def __init__(self, device_path, format):
        self.device_path = device_path
        self.format = format
    
    def photo(self):
        # fswebcam -r 1280x720 -d "/dev/video1" webcam.jpg
        result = subprocess.run(['fswebcam', '-r', self.format, '-d', self.device_path, get_photo_filepath(self) ], capture_output=True, text=True)
        print("Return code:", result.returncode)
        print("Output:", result.stdout)
        print("Error:", result.stderr)


def get_photo_filepath(camera:Camera):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d:%H:%M:%S.%fZ')
    return f"{path_store_photos}/{camera.device_path.replace('/','-')}_{camera.format}_{now}.jpg"


def find_cameras():
    result = subprocess.run(['v4l2-ctl', '--list-devices'], capture_output=True, text=True)
    print("Return code:", result.returncode)
    print("Output:", result.stdout)
    print("Error:", result.stderr)

    result = subprocess.run(['ffmpeg', '-f', 'v4l2', '-list_formats', 'all', '-i', '/dev/video1'], capture_output=True, text=True)
    print("Return code:", result.returncode)
    print("Output:", result.stdout)
    print("Error:", result.stderr)
    

def get_cameras():
    print('get_cameras')
    return []

def take_photo(camera):
    print('photo taken by '+ camera)


def test():
    # find_cameras()
    c = Camera('/dev/video1','2592x1944')
    c.photo()