'''
Verify whether the camera system can respond to commands correctly.
These tests can not verify whether the results are generated correctly, since we need nothing about the correct answer. The correctness test will be done in an environment specific test. such as in `rr_test.py`.

Every test function starts with prefix `test_`, so that pytest can automatically discover these functions during execution.
'''
import time

import unrealcv
from unrealcv import client
from conftest import checker, ver
import numpy as np
import pytest
from io import BytesIO
import os, re
try:
    import cv2
    no_opencv = False
except ImportError:
    no_opencv = True

def imread_png(res):
    import PIL.Image
    PILimg = PIL.Image.open(BytesIO(res))
    return np.array(PILimg)

def imread_npy(res):
    return np.load(BytesIO(res))

def imread_file(res):
    if res[-3:] == 'npy':
        res = np.load(res)
        return res/np.max(res)
    else:
        return cv2.imread(res)


def test_camera_control(cam_id=0):
    client.connect()
    cmds = [
        f'vget /camera/{cam_id}/location',
        f'vget /camera/{cam_id}/rotation',
        # 'vset /camera/0/location 0 0 0', # BUG: If moved out the game bounary, the pawn will be deleted, so that the server code will crash with a nullptr error.
        # 'vset /camera/0/rotation 0 0 0',
    ]
    for cmd in cmds:
        res = client.request(cmd)
        assert checker.not_error(res)

@pytest.mark.skipif(ver() < (0,3,7), reason = 'Png mode is implemented in v0.3.7')
def test_png_mode(cam_id=0):
    '''
    Get image as a png binary, make sure no exception happened
    '''
    client.connect()
    cmds = [
        f'vget /camera/{cam_id}/lit png',
        f'vget /camera/{cam_id}/object_mask png',
        f'vget /camera/{cam_id}/normal png',
    ]
    for cmd in cmds:
        res = client.request(cmd)
        assert checker.not_error(res)
        im = imread_png(res)

@pytest.mark.skipif(ver() < (0,3,8), reason = 'Npy mode is implemented in v0.3.8')
def test_npy_mode(cam_id=0):
    '''
    Get data as a numpy array
    '''
    client.connect()
    cmd = f'vget /camera/{cam_id}/depth npy'
    res = client.request(cmd)
    assert checker.not_error(res)

    # Do these but without assert, if exception happened, this test failed
    arr = imread_npy(res)

@pytest.mark.skipif(no_opencv, reason = 'Can non find OpenCV')
def test_file_mode(cam_id=0, show_img=True):
    ''' Save data to disk as image file '''
    client.connect()
    config_dir = get_config_dir()
    cmds = [
        f'vget /camera/{cam_id}/lit test.png',
        f'vget /camera/{cam_id}/object_mask test.png',
        f'vget /camera/{cam_id}/normal test.png',
        f'vget /camera/{cam_id}/depth test.npy',
    ]
    for cmd in cmds:
        res = client.request(cmd)
        assert checker.not_error(res)
        im = imread_file(os.path.join(config_dir, res))
        if show_img:
            cv2.imshow('img', im)
            cv2.waitKey(10)
            time.sleep(1)

@pytest.mark.skipif(ver() < (0,3,8), reason = 'Npy mode is implemented in v0.3.8')
def get_config_dir():
    '''Get the directory of the unrealcv config file'''
    client.connect()
    res = client.request('vget /unrealcv/status')
    config_file = re.search(r'Config file: (.+?)\n', res).group(1)
    config_directory = os.path.dirname(config_file)
    return config_directory

@pytest.mark.skip(reason = 'Need to explicitly ignore this test for linux')
def test_exr_file():
    cmds = [
        'vget /camera/0/depth test.exr', # This is very likely to fail in Linux
    ]
    client.connect()
    for cmd in cmds:
        res = client.request(cmd)
        assert checker.not_error(res)

        im = imread_file(res)

if __name__ == '__main__':
    unrealcv.client.connect()
    unrealcv.client.request('vset /action/game/level %s' % map)
    res = unrealcv.client.request('vget /cameras')
    checker.not_error(res)
    camera_num = len(res.split())
    for cam_id in range(camera_num): # Test all cameras in the level
        test_png_mode(cam_id)
        test_npy_mode(cam_id)
        test_file_mode(cam_id)
    unrealcv.client.disconnect()
    exit()
