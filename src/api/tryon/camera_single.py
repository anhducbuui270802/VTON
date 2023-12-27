# import cv2

# class Camera():
#     def __init__(self):
#         self.video = cv2.VideoCapture(0)

#     def __del__(self):
#         self.video.release()

#     def get_frame(self):
#         success, image = self.video.read()
#         ret, jpeg = cv2.imencode('.jpg', image)
#         return jpeg.tobytes()

import cv2
import time

class Camera():
    def __init__(self):
        self.video = cv2.VideoCapture(0)

    def __del__(self):
        self.video.release()

    def get_frame(self, fps=20):
        interval = 1.0 / fps
        last_frame_time = time.time()
        current_time = time.time()
        elapsed_time = current_time - self.last_frame_time

        if elapsed_time > self.interval:
            success, image = self.video.read()
            if success:
                ret, jpeg = cv2.imencode('.jpg', image)
                self.last_frame_time = current_time
                return jpeg.tobytes()

        return None