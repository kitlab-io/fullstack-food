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

class CameraUSB:
    def __init__(self, device_path, format):
        self.device_path = device_path # '/dev/video1'
        self.format = format # '2592x1944'
    
    def photo(self):
        # fswebcam -r 1280x720 -d "/dev/video1" webcam.jpg
        photo_filepath = get_photo_filepath(self)
        result = subprocess.run(['fswebcam', '-r', self.format, '-d', self.device_path, photo_filepath ], capture_output=True, text=True)
        print("Return code:", result.returncode)
        print("Output:", result.stdout)
        print("Error:", result.stderr)

        return photo_filepath, self.device_path, self.format

def get_photo_filepath(camera:CameraUSB):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d:%H:%M:%S.%fZ')
    return f"{path_store_photos}/{camera.device_path.replace('/','-')}_{camera.format}_{now}.jpg"


def find_cameras():
    result = subprocess.run(['v4l2-ctl', '--list-devices'], capture_output=True, text=True)
    print("Return code:", result.returncode)
    print("Output:", result.stdout)
    print("Error:", result.stderr)
    
    # """USB Cam: USB Cam (usb-5200000.usb-1.2): 
    #  /dev/video1"""

    device_paths = extract_usb_cam_device(result.stdout)
    print(device_paths)  # Should print: /dev/video1


def get_camera_formats():
    result = subprocess.run(['ffmpeg', '-f', 'v4l2', '-list_formats', 'all', '-i', '/dev/video1'], capture_output=True, text=True)
    print("Return code:", result.returncode)
    print("Output:", result.stdout)
    print("Error:", result.stderr)
    
    # Test with sample input
    # sample_text = "[video4linux2,v4l2 @ 0xaaaab2fa08c0] Compressed:       mjpeg :          Motion-JPEG : 640x480 320x240 352x288 640x480 800x600 1280x720 1920x1080 1600x1200 2048x1536 2592x1944"
    highest_resolution = extract_last_resolution(result.stdout)
    print(highest_resolution)  # Should print: 2592x1944
    
    return highest_resolution


def extract_last_resolution(text):
    # Find all resolution patterns in the format NNNNxNNNN
    import re
    resolution_pattern = r'(\d+x\d+)'
    resolutions = re.findall(resolution_pattern, text)
    if resolutions:
        return resolutions[-1]
    else:
        return None


# USB Camera board from Aliepxress
target_camera_devices = "USB Cam: USB Cam (usb-5200000.usb-1.2):"

def extract_usb_cam_device(text):
    device_paths = []
    lines = text.splitlines()
    for i in range(len(lines)):
        if target_camera_devices in lines[i]:
            # Look at subsequent lines for first non-whitespace line
            if lines[i+1].strip():
                    device_paths.append({
                        "name": target_camera_devices,
                        "path": lines[i+1].strip()
                        })
        
    return device_paths


    

def get_cameras():
    print('get_cameras')
    return []

def take_photo(camera):
    print('photo taken by '+ camera)


def test():
    # find_cameras()
    c = CameraUSB('/dev/video1','2592x1944')
    c.photo()