import os
import threading
import time
import datetime
import subprocess
import warnings
from collections import deque
from typing import Optional, Dict
import numpy as np
from scipy.io.wavfile import write as write_wav
from milkchan.bootstrap import get_user_data_dir

RECORDINGS_DIR = os.path.join(str(get_user_data_dir()), 'recordings')
TEMP_DIR = os.path.join(RECORDINGS_DIR, 'temp')
os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

cv2 = None
sc = None


class BackgroundRecorder:
    def __init__(self, config: Dict, buffer_seconds: int = None, fps: int = 24):
        self.config = config
        self.processing_config = self.config.get('processing', {})
        self.vision_enabled = self.processing_config.get('vision_enabled', True)
        self.audio_enabled = self.processing_config.get('audio_enabled', True)
        self.video_resize_factor = self.processing_config.get('video_resize_factor', 0.35)
        self.buffer_seconds = buffer_seconds or self.processing_config.get('buffer_seconds', 10)
        self.fps = fps
        self.frame_buffer = deque(maxlen=self.buffer_seconds * fps)
        self.audio_buffer = deque(maxlen=self.buffer_seconds * 43)
        self.recording = False
        self.lock = threading.Lock()
        self.audio_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.recording_thread = None
        self.audio_recording_thread = None
        self.audio_samplerate = 44100
        self.audio_channels = 2
        self.selected_speaker = None
        self.audio_capture_failed = False

    def _suppress_soundcard_warnings(self):
        try:
            from soundcard import SoundcardRuntimeWarning as SCWarn
            warnings.filterwarnings("ignore", category=SCWarn)
        except Exception:
            # Best-effort; if class is not available yet or import fails, ignore.
            pass

    def _setup_audio_device(self) -> bool:
        if not self.audio_enabled:
            return False
        global sc
        if not sc:
            try:
                import soundcard as sc  # dynamic import
                self._suppress_soundcard_warnings()
            except Exception:
                print('Soundcard not available')
                return False
        try:
            self.selected_speaker = sc.default_speaker()
            if not self.selected_speaker:
                return False
            ch = getattr(self.selected_speaker, 'channels', 2)
            self.audio_channels = ch if isinstance(ch, int) and ch > 0 else 2
            return True
        except Exception:
            return False

    def start_recording(self):
        if not self.vision_enabled or self.recording:
            return
        self.stop_flag.clear()
        self.recording = True
        self.recording_thread = threading.Thread(target=self._record_video_loop, daemon=True)
        self.recording_thread.start()
        if self._setup_audio_device():
            self.audio_recording_thread = threading.Thread(target=self._record_audio_loop, daemon=True)
            self.audio_recording_thread.start()
        else:
            self.audio_capture_failed = True

    def stop_recording(self):
        if not self.recording:
            return
        self.stop_flag.set()
        if self.recording_thread:
            self.recording_thread.join(timeout=2)
        if self.audio_recording_thread:
            self.audio_recording_thread.join(timeout=2)
        self.recording = False

    def _record_audio_loop(self):
        global sc
        if not sc or self.selected_speaker is None:
            self.audio_capture_failed = True
            return
        # Larger blocksize helps reduce discontinuity warnings
        blocksize = 4096
        try:
            mic = sc.get_microphone(id=self.selected_speaker.id, include_loopback=True)
            # Suppress soundcard runtime warnings inside loop as well (belt & suspenders)
            self._suppress_soundcard_warnings()
            with mic.recorder(samplerate=self.audio_samplerate, channels=self.audio_channels, blocksize=blocksize) as recorder:
                while not self.stop_flag.is_set():
                    try:
                        data = recorder.record(numframes=blocksize)
                        if data is not None and getattr(data, 'size', 0) > 0:
                            with self.audio_lock:
                                self.audio_buffer.append(data)
                    except Exception:
                        # Drop bad chunks silently
                        continue
        except Exception as e:
            print(f'Audio loop failed: {e}')
            self.audio_capture_failed = True

    def _record_video_loop(self):
        global cv2
        if not cv2:
            try:
                import cv2 as _cv2
                globals()['cv2'] = _cv2
            except Exception:
                print('OpenCV not available; video disabled.')
                return
        try:
            import mss, numpy as np
        except Exception:
            print('mss/numpy not available; video disabled.')
            return
        frame_time = 1.0 / self.fps
        with mss.mss() as sct:
            mon = sct.monitors[1]
            bbox = {"top": mon['top'], "left": mon['left'], "width": mon['width'], "height": mon['height']}
            while not self.stop_flag.is_set():
                t0 = time.perf_counter()
                img_mss = sct.grab(bbox)
                frame = cv2.cvtColor(np.array(img_mss), cv2.COLOR_BGRA2BGR)
                if self.video_resize_factor != 1.0:
                    h, w, _ = frame.shape
                    new_w = max(2, int(w * self.video_resize_factor))
                    new_h = max(2, int(h * self.video_resize_factor))
                    new_w -= new_w % 2
                    new_h -= new_h % 2
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                with self.lock:
                    self.frame_buffer.append(frame)
                sleep = frame_time - (time.perf_counter() - t0)
                if sleep > 0:
                    time.sleep(sleep)

    def save_buffer(self, filename: Optional[str] = None) -> Optional[str]:
        global cv2
        if not self.recording or not cv2:
            return None
        with self.lock:
            frames = list(self.frame_buffer)
        if not frames:
            return None
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        filename = filename or f'message_recording_{timestamp}.mp4'
        full_path = os.path.join(RECORDINGS_DIR, filename)
        temp_video_path = os.path.join(TEMP_DIR, f'temp_video_{timestamp}.avi')
        temp_audio_path = os.path.join(TEMP_DIR, f'temp_audio_{timestamp}.wav')
        h, w, _ = frames[0].shape
        w, h = w - (w % 2), h - (h % 2)
        try:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, (w, h))
            if not out.isOpened():
                raise IOError('Could not open video writer.')
            for frame in frames:
                if frame.shape[1] != w or frame.shape[0] != h:
                    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                out.write(frame)
        except Exception as e:
            print(f'Error writing temp video: {e}')
            return None
        finally:
            if 'out' in locals() and out.isOpened():
                out.release()
        has_audio = self._save_audio_buffer(temp_audio_path)
        cmd = ['ffmpeg', '-y', '-i', temp_video_path]
        if has_audio:
            cmd.extend(['-i', temp_audio_path])
        cmd.extend(['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-pix_fmt', 'yuv420p'])
        if has_audio:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k', '-shortest'])
        cmd.append(full_path)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
            return full_path
        except Exception as e:
            print(f'ffmpeg error: {e}')
            return None
        finally:
            for p in (temp_video_path, temp_audio_path):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    def save_tail(self, seconds: int = 4, filename: Optional[str] = None) -> Optional[str]:
        """
        Save a short clip from the last `seconds` of the buffer (video + audio).
        Ensures at least seconds * fps frames by briefly waiting and padding if needed.
        Returns the mp4 file path or None if failed.
        """
        global cv2
        if not self.recording or not cv2:
            return None
        seconds_int = max(1, min(int(seconds or 4), self.buffer_seconds))

        # Wait briefly for enough frames to ensure at least seconds*fps frames
        target_frames = seconds_int * self.fps
        t_start = time.perf_counter()
        while True:
            with self.lock:
                available = len(self.frame_buffer)
            if available >= target_frames or (time.perf_counter() - t_start) >= seconds_int:
                break
            time.sleep(0.01)

        with self.lock:
            frames = list(self.frame_buffer)
        if not frames:
            return None

        if len(frames) >= target_frames:
            clip_frames = frames[-target_frames:]
        else:
            # Not enough frames captured yet; pad by repeating last frame
            clip_frames = frames[:]
            last_frame = clip_frames[-1]
            while len(clip_frames) < target_frames:
                clip_frames.append(last_frame)
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        filename = filename or f'proactive_tail_{timestamp}.mp4'
        full_path = os.path.join(RECORDINGS_DIR, filename)
        temp_video_path = os.path.join(TEMP_DIR, f'temp_tail_{timestamp}.avi')
        h, w, _ = clip_frames[0].shape
        w, h = w - (w % 2), h - (h % 2)
        try:
            fourcc = cv2.VideoWriter_fourcc(*'XVID')
            out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, (w, h))
            if not out.isOpened():
                raise IOError('Could not open video writer for tail clip.')
            for frame in clip_frames:
                if frame.shape[1] != w or frame.shape[0] != h:
                    frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
                out.write(frame)
        except Exception as e:
            print(f'Error writing temp tail video: {e}')
            return None
        finally:
            if 'out' in locals() and out.isOpened():
                out.release()
        # Optionally add audio tail if available
        temp_audio_path = os.path.join(TEMP_DIR, f'temp_tail_audio_{timestamp}.wav')
        has_audio = self._save_audio_tail(temp_audio_path, seconds_int)
        # Transcode to mp4, include audio if present
        cmd = ['ffmpeg', '-y', '-i', temp_video_path]
        if has_audio:
            cmd.extend(['-i', temp_audio_path])
        cmd.extend(['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-pix_fmt', 'yuv420p'])
        if has_audio:
            cmd.extend(['-c:a', 'aac', '-b:a', '128k', '-shortest'])
        cmd.append(full_path)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=20)
            return full_path
        except Exception as e:
            print(f'ffmpeg tail error: {e}')
            return None
        finally:
            if os.path.exists(temp_video_path):
                try:
                    os.remove(temp_video_path)
                except OSError:
                    pass
            if has_audio and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except OSError:
                    pass

    def _save_audio_buffer(self, path: str) -> bool:
        if self.audio_capture_failed or not self.audio_buffer:
            return False
        with self.audio_lock:
            chunks = list(self.audio_buffer)
        if not chunks:
            return False
        try:
            import numpy as np
            full_audio = np.concatenate(chunks, axis=0)
            scaled = (np.clip(full_audio, -1.0, 1.0) * 32767).astype(np.int16)
            write_wav(path, self.audio_samplerate, scaled)
            return True
        except Exception as e:
            print(f'audio buffer error: {e}')
            return False

    def _save_audio_tail(self, path: str, seconds: int) -> bool:
        if self.audio_capture_failed:
            return False
        with self.audio_lock:
            chunks = list(self.audio_buffer)
        if not chunks:
            return False
        try:
            import numpy as np
            target_frames = int(max(1, seconds) * self.audio_samplerate)
            acc = []
            frames = 0
            # accumulate from the end until we reach target duration
            for arr in reversed(chunks):
                if arr is None:
                    continue
                frames += arr.shape[0]
                acc.append(arr)
                if frames >= target_frames:
                    break
            if not acc:
                return False
            acc.reverse()
            full_audio = np.concatenate(acc, axis=0)
            if full_audio.shape[0] > target_frames:
                full_audio = full_audio[-target_frames:]
            scaled = (np.clip(full_audio, -1.0, 1.0) * 32767).astype(np.int16)
            write_wav(path, self.audio_samplerate, scaled)
            return True
        except Exception as e:
            print(f'audio tail error: {e}')
            return False