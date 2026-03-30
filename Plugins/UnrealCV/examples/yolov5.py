'''
This script is an example of using YOLOv5 (Pytorch) with UnrealCV.
To install YOLOv5, you can refer to this page: https://pytorch.org/hub/ultralytics_yolov5/
'''

import unrealcv
from unrealcv.util import read_png
import torch
import cv2

if __name__ == '__main__':
    client = unrealcv.Client(('localhost', 9000))  # config the port according to your setting
    client.connect()
    model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True)
    for i in range(1000):
        res = client.request('vget /camera/0/lit png')
        img = read_png(res)
        results = model([img])
        img = results.render()[0]
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        cv2.imshow('img', img)
        if cv2.waitKey(20) & 0xFF == ord('q'):
            break
    client.disconnect()

