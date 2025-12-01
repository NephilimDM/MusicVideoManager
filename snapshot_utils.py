import cv2
import numpy as np


class SnapshotUtils:
    """Utilities for video frame extraction and processing."""

    @staticmethod
    def extract_frame(video_path, output_path, position_percent=0.20):
        """
        Extract a frame from the video at a specific percentage duration.

        Args:
            video_path (str): Path to the video file.
            output_path (str): Path to save the extracted image.
            position_percent (float): Position in video (0.0 to 1.0). Default 0.20 (20%).

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print(
                    f"DEBUG: Impossibile aprire video per snapshot: {video_path}")
                return False

            # Calculate position
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            target_frame = int(total_frames * position_percent)

            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            ret, frame = cap.read()

            if ret:
                # Smart Upscaling: Ensure minimum 1920px width for Fanart
                height, width = frame.shape[:2]
                target_width = 1920

                if width < target_width:
                    # Calculate aspect ratio and new height
                    aspect_ratio = height / width
                    new_height = int(target_width * aspect_ratio)

                    # Upscale using high-quality LANCZOS4 interpolation
                    frame = cv2.resize(
                        frame, (target_width, new_height),
                        interpolation=cv2.INTER_LANCZOS4)
                    print(
                        f"📐 Upscaled da {width}x{height} a {target_width}x{new_height}")

                cv2.imwrite(output_path, frame)
                print(f"📸 Generato Snapshot locale per fanart: {output_path}")
                cap.release()
                return True
            else:
                print(f"DEBUG: Errore lettura frame per {video_path}")
                cap.release()
                return False
        except (OSError, ValueError) as e:
            print(f"DEBUG: Errore estrazione frame: {e}")
            return False
        except Exception as e:
            print(f"DEBUG: Errore generico estrazione frame: {e}")
            return False
