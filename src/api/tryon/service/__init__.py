from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image
from torch.autograd import Variable

from .dm_vton import DMVTON, get_transform
from .segment import MediapipeSegmentation
from .u2net import load_model as load_edge_detect_model
from .u2net import norm_pred
from .yolov7_pose import Yolov7PoseEstimation

face_classifier = cv2.CascadeClassifier('./Cascade/haarcascade_frontalface_default.xml')

class TryonService:
    def __init__(
        self,
        tryon_ckpt,
        edge_detect_ckpt,
        yolo_ckpt,
        mediapipe_segment_ckpt,
        device,
        img_size=(192, 256),
    ) -> None:
        self.device = device
        self.img_size = img_size
        self._load_model(tryon_ckpt, edge_detect_ckpt, device=device)
        self._load_yolov7(yolo_ckpt)
        self._load_mediapipe_segmenter(mediapipe_segment_ckpt)
        self._load_transforms()

    @torch.no_grad()
    def tryon_image(self, pil_img, pil_clothes, pil_edge=None) -> Any:
        image = np.asarray(pil_img)

        image, image_with_background, mask = self._remove_background(image, threshold=0.5)
        cropped_result, frame = self._preprocess_frame(image)

        if frame is None:
            return None

        transform_image = get_transform(train=False)
        transform_edge = get_transform(train=False, method=Image.NEAREST, normalize=False)

        pil_img = Image.fromarray(frame)
        pil_clothes = self._preprocess_image(pil_clothes)

        img = transform_image(pil_img)
        clothes = transform_image(pil_clothes)
        if pil_edge:
            clothes_edge = self._preprocess_image(pil_clothes, color='L')
            clothes_edge = transform_edge(clothes_edge)
        else:
            clothes_edge = self._predict_edge(clothes)

        cv_img = (
            self._predict_tryon(img, clothes, clothes_edge).permute(1, 2, 0).detach().cpu().numpy()
            + 1
        ) / 2
        rgb = (cv_img * 255).astype(np.uint8)

        top, left, bottom, right = (
            cropped_result['top'],
            cropped_result['left'],
            cropped_result['bottom'],
            cropped_result['right'],
        )
        cropped_output = cv2.resize(rgb, (right - left, bottom - top))
        output = image.copy()
        output[top:bottom, left:right, :] = cropped_output

        output = (output * mask + image_with_background * (1 - mask)).astype(np.uint8)
        return output
    
    @torch.no_grad()
    def tryon_video(self, cap, pil_clothes, pil_edge=None, fps=30):
        transform_image = get_transform(train=False)
        transform_edge = get_transform(train=False, method=Image.NEAREST, normalize=False)

        # save_name = f'{datetime.datetime.now().strftime("%Y-%m-%d_%H%M-%S")}.mp4'
        save_name = 'aaaa.mp4'
        vid_writer = cv2.VideoWriter(save_name, cv2.VideoWriter_fourcc(*'mp4v'), fps, self.img_size)

        pil_clothes = self._preprocess_image(pil_clothes)

        clothes = transform_image(pil_clothes)
        if pil_edge is not None:
            clothes_edge = self._preprocess_image(pil_clothes, color='L')
            clothes_edge = transform_edge(clothes_edge)
        else:
            clothes_edge = self._predict_edge(clothes)

        idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if ret is True:
                frame = frame[:, :, :]
                cropped_result, frame = self._preprocess_frame(frame)
                if frame is not None:
                    pil_img = Image.fromarray(frame)
                    img = transform_image(pil_img)

                # TRYON
                original_image = cropped_result['origin_frame']
                if frame is not None:
                    cv_img = (
                        self._predict_tryon(img, clothes, clothes_edge)
                        .permute(1, 2, 0)
                        .detach()
                        .cpu()
                        .numpy()
                        + 1
                    ) / 2
                    rgb = (cv_img * 255).astype(np.uint8)
                    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

                    # Re-mapping to original image
                    top, left, bottom, right = (
                        cropped_result['top'],
                        cropped_result['left'],
                        cropped_result['bottom'],
                        cropped_result['right'],
                    )
                    cropped_output = cv2.resize(bgr, (right - left, bottom - top))
                    original_image[top:bottom, left:right, :] = cropped_output

                idx += 1
                # cv2.imwrite(f"{idx}.jpg", original_image)
                vid_writer.write(original_image)
            else:
                break
    @torch.no_grad()
    def gen(self, camera, pil_clothes, pil_edge=None, fps=30):
        """Video streaming generator function."""
        transform_image = get_transform(train=False)
        transform_edge = get_transform(train=False, method=Image.NEAREST, normalize=False)
        pil_clothes = self._preprocess_image(pil_clothes)
        clothes = transform_image(pil_clothes)
        if pil_edge is not None:
            clothes_edge = self._preprocess_image(pil_clothes, color='L')
            clothes_edge = transform_edge(clothes_edge)
        else:
            clothes_edge = self._predict_edge(clothes)

        while camera.isOpened():
            success, frame = camera.get_frame()
            if success is True:
                frame = frame[:, :, :]
                cropped_result, frame = self._preprocess_frame(frame)
                if frame is not None:
                    pil_img = Image.fromarray(frame)
                    img = transform_image(pil_img)

                # TRYON
                original_image = cropped_result['origin_frame']
                if frame is not None:
                    cv_img = (
                        self._predict_tryon(img, clothes, clothes_edge)
                        .permute(1, 2, 0)
                        .detach()
                        .cpu()
                        .numpy()
                        + 1
                    ) / 2
                    rgb = (cv_img * 255).astype(np.uint8)
                    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

                    # Re-mapping to original image
                    top, left, bottom, right = (
                        cropped_result['top'],
                        cropped_result['left'],
                        cropped_result['bottom'],
                        cropped_result['right'],
                    )
                    cropped_output = cv2.resize(bgr, (right - left, bottom - top))
                    original_image[top:bottom, left:right, :] = cropped_output

                ret, jpeg = cv2.imencode('.jpg', original_image)
                original_image = jpeg.tobytes()
                yield (b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + original_image + b'\r\n')

    def _preprocess_image(self, pil_img, color='RGB'):
        pil_img = pil_img.convert(color).resize(self.img_size)
        return pil_img

    def _preprocess_frame(self, frame):
        # Crop the image using pose
        cropped_result = crop_upper_body(frame, self.yolo_model)
        frame = cropped_result['cropped_frame']

        if frame is None:
            return cropped_result, None

        # Crop the image to have same ratio
        if frame.shape[0] * self.img_size[0] < frame.shape[1] * self.img_size[1]:
            height = frame.shape[0]
            width = int(self.img_size[0] * height / self.img_size[1])
        else:
            width = frame.shape[1]
            height = int(self.img_size[1] * width / self.img_size[0])

        center = (frame.shape[0] // 2, frame.shape[1] // 2)
        x = center[1] - width // 2
        y = center[0] - height // 2
        frame = frame[y : y + height, x : x + width]
        frame = cv2.resize(frame, (self.img_size[0], self.img_size[1]))

        # Mapping bbox value
        cropped_result['top'] += y
        cropped_result['bottom'] = cropped_result['top'] + height
        cropped_result['left'] += x
        cropped_result['right'] = cropped_result['left'] + width

        return cropped_result, frame

    def _remove_background(self, frame, threshold=0.5):
        mask = self.mediapipe_segmenter.predict(frame, threshold)
        result = (frame * mask + 255 * (1 - mask)).astype(np.uint8)
        return result, frame, mask

    def _load_model(self, tryon_ckpt, edge_detect_ckpt, device):
        self.tryon_model = DMVTON(tryon_ckpt, device=device, align_corners=True)
        self.edge_detect_model = load_edge_detect_model(
            model_name='u2netp', checkpoint=edge_detect_ckpt, device=device
        )

    def _load_transforms(self):
        self.transform_image = get_transform(train=False)
        self.transform_edge = get_transform(train=False, method=Image.NEAREST, normalize=False)

    def _predict_edge(self, img):
        img = img.clone().unsqueeze(0)
        img = img.type(torch.FloatTensor)

        img = Variable(img.to(self.device))

        with torch.no_grad():
            d1 = self.edge_detect_model(img)

        pred_mask = d1[:, 0, :, :]
        pred_mask = norm_pred(pred_mask)

        return pred_mask

    def _predict_tryon(self, img, clothes, clothes_edge):
        img = img.clone().unsqueeze(0)
        clothes = clothes.clone().unsqueeze(0)
        clothes_edge = clothes_edge.clone().unsqueeze(0)

        with torch.no_grad():
            p_tryon = self.tryon_model(img, clothes, clothes_edge)

        return p_tryon[0]

    def _load_yolov7(self, yolo_ckpt):
        self.yolo_model = Yolov7PoseEstimation(
            weight_path=yolo_ckpt,
            device=self.device,
        )

    def _load_mediapipe_segmenter(self, mediapipe_segment_ckpt):
        self.mediapipe_segmenter = MediapipeSegmentation(model_path=mediapipe_segment_ckpt)


def crop_upper_body(frame, pose_detector):
    results = pose_detector.process(frame)
    h, w, _ = frame.shape

    # TUNGPNT2
    if results.pose_landmarks is None:
        return {
            'origin_frame': frame,
            'cropped_frame': None,
            'top': 0,
            'left': 0,
            'bottom': 0,
            'right': 0,
        }

    landmarks = results.pose_landmarks.landmark

    # 2 lower points of upper body
    l1 = {'x': landmarks[23].x, 'y': landmarks[23].y}
    l2 = {'x': landmarks[24].x, 'y': landmarks[24].y}

    # 2 eyes
    e1 = {'x': landmarks[2].x, 'y': landmarks[2].y}
    e2 = {'x': landmarks[5].x, 'y': landmarks[5].y}

    points = [l1, l2, e1, e2]

    # bbox
    top = min([i['y'] for i in points])
    bottom = max([i['y'] for i in points])
    left = min([i['x'] for i in points])
    right = max([i['x'] for i in points])

    # de-normalize
    top = int(top * h)
    bottom = int(bottom * h)
    left = int(left * w)
    right = int(right * w)

    # padding
    bh = bottom - top
    bw = right - left
    bottom += bh // 5
    top -= bh // 5
    right += bw // 1
    left -= bw // 1

    # crop
    top = max(0, min(top, h))
    bottom = max(0, min(bottom, h))
    left = max(0, min(left, w))
    right = max(0, min(right, w))

    return {
        'origin_frame': frame,
        'cropped_frame': frame[top:bottom, left:right, :],
        'top': top,
        'left': left,
        'bottom': bottom,
        'right': right,
    }
