# main_app/agents/agent_workers.py
import os
import time
import traceback
import threading
import hashlib
import random
from typing import Any, Dict, List, Optional, Tuple, TypedDict
from collections import deque

from PyQt5.QtCore import QThread, pyqtSignal

from milkchan.desktop.services import ai_client, memory_client
from milkchan.core.config import load_config
from milkchan.desktop.utils.screenshot import take_screenshot, downscale_image_for_upload
from PIL import Image, ImageChops
from milkchan.desktop.utils.highlights import detect_highlight


class SendMessageResult(TypedDict):
    response: str
    emotion: Optional[Dict]
    error: Optional[Dict]


def send_message(message: str, video_filepath: Optional[str] = None) -> SendMessageResult:
    """Send a message to the AI and get response with emotion."""
    t0 = time.perf_counter()
    print(f"[send_message] start; text_len={len(message)}; has_video={bool(video_filepath)}")

    config = load_config()
    processing = (config.get('processing') or {})

    history = memory_client.get_history()

    vision_mode = processing.get('vision_mode') or ('video' if processing.get('vision_enabled', True) else 'image')
    ss_when_disabled = bool(processing.get('screenshot_on_disabled_vision', True))

    screenshot_path = None
    width = height = None
    should_screenshot = bool(message) and (
        vision_mode in ('video', 'image') or
        (not processing.get('vision_enabled', True) and ss_when_disabled)
    )
    if should_screenshot:
        try:
            rf = float(processing.get('video_resize_factor', 0.35))
        except Exception:
            rf = 1.0
        try:
            ss = take_screenshot(rf)
            if ss:
                screenshot_path, width, height = ss
                print(f"[send_message] screenshot: {screenshot_path} ({width}x{height}) rf={rf}")
        except Exception:
            traceback.print_exc()

    user_message_for_ai = message

    image_to_send = screenshot_path
    proc_cfg = (config.get('processing') or {})
    if image_to_send and os.path.exists(image_to_send):
        rf = float(proc_cfg.get('video_resize_factor', 0.35))
        max_dim = max(600, int(1200 * min(1.0, max(0.25, rf))))
        image_to_send = downscale_image_for_upload(image_to_send, max_dim=max_dim)

    print("[MSG]", history, user_message_for_ai)
    result = ai_client.chat_respond(
        user_message=user_message_for_ai,
        history=history,
        username=config.get('username', 'User'),
        image_path=image_to_send,
        timeout_sec=float(proc_cfg.get('chat_timeout_sec', 0)) or None
    )
    
    model_message = result.get('response', '')
    emotion = result.get('emotion')
    error = result.get('error')
    
    try:
        if image_to_send and screenshot_path and image_to_send != screenshot_path and os.path.exists(image_to_send):
            os.remove(image_to_send)
    except Exception:
        pass
    
    if error:
        print(f"[send_message] chat_respond error: {error.get('type')} - {error.get('message')}")
    else:
        print(f"[send_message] chat_respond done in {time.perf_counter()-t0:.2f}s; reply_len={len(model_message)}")

    if not error:
        history.append({'role': 'user', 'content': message})
        history.append({'role': 'assistant', 'content': model_message})
        memory_client.update_history(history)
        print(f"[send_message] saved {len(history)} messages to history")

    if video_filepath and os.path.exists(video_filepath):
        try:
            os.remove(video_filepath)
        except OSError:
            pass
    if screenshot_path:
        try:
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
        except OSError:
            pass

    print(f"[send_message] done in {time.perf_counter()-t0:.2f}s")
    return SendMessageResult(response=model_message, emotion=emotion, error=error)


def _percent_image_diff(path_a: str, path_b: str, resize_side: int = 256) -> float:
    """
    Quick pixel-difference percent between two images.
    Resize both to (resize_side x resize_side) for speed, compute sum(|diff|) normalized to [0,100].
    Returns percent changed (0.0..100.0). On error, returns 100.0 (conservative).
    """
    # Retry open in case of transient file locks
    def _open_with_retry(p):
        for _ in range(3):
            try:
                return Image.open(p)
            except Exception:
                time.sleep(0.05)
        return None

    try:
        if not path_a or not path_b or not os.path.exists(path_a) or not os.path.exists(path_b):
            return 100.0
        A = _open_with_retry(path_a)
        B = _open_with_retry(path_b)
        if A is None or B is None:
            return 100.0
        try:
            A = A.convert('RGB').resize((resize_side, resize_side), Image.LANCZOS)
            B = B.convert('RGB').resize((resize_side, resize_side), Image.LANCZOS)
            diff = ImageChops.difference(A, B).convert('L')  # grayscale diff
            hist = diff.histogram()
            total = sum(i * hist[i] for i in range(256))
            max_total = 255 * resize_side * resize_side
            percent = (total / float(max_total)) * 100.0
            return percent
        finally:
            try:
                A.close()
            except Exception:
                pass
            try:
                B.close()
            except Exception:
                pass
    except Exception as e:
        print(f"[agent_workers._percent_image_diff] error: {e}")
        return 100.0

def _safe_remove(path: Optional[str]):
    if not path:
        return
    for _ in range(5):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except Exception:
            time.sleep(0.05)


def send_semantic_proactive(change_summary: str, image_filepath: Optional[str]) -> SendMessageResult:
    """
    Generates a short, friendly proactive message reacting to a detected screen change.
    Optionally includes a screenshot (image_filepath) for added context.
    Uses single API call with tool-based sprite update (no separate emotion analysis).
    """
    t0 = time.perf_counter()
    print(f"[send_semantic_proactive] [{time.strftime('%H:%M:%S')}] start; change_summary={change_summary!r}; has_image={bool(image_filepath)}")

    config = load_config()
    history = memory_client.get_history()

    user_message_for_ai = (
        f"Screen change detected: {change_summary} | "
        "Respond in 2-3 in-character sentences as MilkChan."
    )

    image_to_send = image_filepath
    try:
        if image_filepath and os.path.exists(image_filepath):
            rf = float((config.get('processing') or {}).get('video_resize_factor', 0.35))
            max_dim = max(600, int(1200 * min(1.0, max(0.25, rf))))
            image_to_send = downscale_image_for_upload(image_filepath, max_dim=max_dim)

        result = ai_client.chat_respond(
            user_message=user_message_for_ai,
            history=history,
            username=config.get('username', 'User'),
            image_path=image_to_send,
        )
    finally:
        try:
            if image_to_send and image_filepath and image_to_send != image_filepath and os.path.exists(image_to_send):
                os.remove(image_to_send)
        except Exception:
            pass
    
    model_message = result.get('response', '')
    emotion = result.get('emotion')
    error = result.get('error')
    
    if error:
        print(f"[send_semantic_proactive] error: {error.get('type')} - {error.get('message')}")
    else:
        print(f"[send_semantic_proactive] chat_respond in {time.perf_counter()-t0:.2f}s; reply_len={len(model_message)}; reply={model_message!r}")
        history.append({'role': 'user', 'content': f"(system) Screen change: {change_summary}"})
        history.append({'role': 'assistant', 'content': model_message})
        memory_client.update_history(history)

    return SendMessageResult(response=model_message, emotion=emotion, error=error)


class SaveAndSendWorker(QThread):
    response_ready = pyqtSignal(str, object)
    error = pyqtSignal(dict)
    emotion_ready = pyqtSignal(object)

    def __init__(self, recorder, text: str):
        super().__init__()
        self.recorder = recorder
        self.text = text
        self._emo_worker = None

    def run(self):
        try:
            print("[SaveAndSendWorker] sending message (fast path)...")
            result = send_message(self.text, None)
            print("[SaveAndSendWorker] response ready.")
            
            if result.get('error'):
                self.error.emit(result['error'])
            else:
                self.response_ready.emit(result.get('response', ''), result.get('emotion'))
        except Exception as e:
            import traceback as _tb
            print("[SaveAndSendWorker] error:", e)
            self.error.emit({
                'type': 'worker_error',
                'message': str(e),
                'details': _tb.format_exc()
            })


class ProactiveMessageWorker(QThread):
    response_ready = pyqtSignal(str, object)
    error = pyqtSignal(dict)

    def __init__(self, recorder):
        super().__init__()
        self.recorder = recorder

    def run(self):
        try:
            print("[ProactiveMessageWorker] saving tail and generating proactive message...")
            video_tail = None
            try:
                video_tail = self.recorder.save_tail(seconds=4)
            except Exception:
                video_tail = None
            description = None
            if video_tail and os.path.exists(video_tail):
                try:
                    description = ai_client.describe_video_tail(video_tail, seconds=4)
                    if description:
                        try:
                            print(f"[ProactiveMessageWorker] video_tail_description: {description}")
                            if "Audio transcript:" in description:
                                _parts = description.split("Audio transcript:", 1)
                                if len(_parts) == 2:
                                    print(f"[ProactiveMessageWorker] audio_transcript: {_parts[1].strip()}")
                        except Exception:
                            pass
                except Exception:
                    description = None
            user_msg = f"[Recent activity: {description}]" if description else "[no input...]"
            result = send_message(user_msg, video_tail)
            
            if result.get('error'):
                self.error.emit(result['error'])
            else:
                print("[ProactiveMessageWorker] proactive response ready")
                self.response_ready.emit(result.get('response', ''), result.get('emotion'))
        except Exception as e:
            import traceback as _tb
            print("[ProactiveMessageWorker] error:", e)
            self.error.emit(f"Error in proactive worker: {e}\n{_tb.format_exc()}")


class SemanticProactiveWorker(QThread):
    response_ready = pyqtSignal(str, object)
    error = pyqtSignal(str)
    # Ensure only one proactive send (single or continuous) is active globally at a time
    _global_send_lock = threading.Lock()

    def __init__(self, before_path: Optional[str] = None, after_path: Optional[str] = None, hint: str = ""):
        super().__init__()
        self.before_path = before_path
        self.after_path = after_path
        self.hint = hint or ""
        self._stop_requested = False
        self._continuous_mode = before_path is None and after_path is None

        # Dedupe / concurrency controls
        self._in_progress = False
        self._lock = threading.Lock()
        self._last_sent_fingerprint = None
        self._last_emit_ts = 0.0

    def stop(self):
        self._stop_requested = True

    def run(self):
        if self._continuous_mode:
            self._run_continuous()
        else:
            self._run_single()

    def _fingerprint_file(self, path: str) -> Optional[str]:
        try:
            h = hashlib.sha1()
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception as e:
            print(f"[SemanticProactiveWorker] fingerprint error: {e}")
            return None

    def _should_throttle_or_dedupe(self, fingerprint: Optional[str], min_interval: float) -> bool:
        now_ts = time.time()
        if self._in_progress:
            print("[SemanticProactiveWorker] send already in progress; skipping this detection.")
            return True
        if fingerprint and self._last_sent_fingerprint == fingerprint and (now_ts - self._last_emit_ts) < min_interval:
            print("[SemanticProactiveWorker] fingerprint matches recent emit; skipping duplicate proactive message.")
            return True
        return False

    def _mark_sent(self, fingerprint: Optional[str]):
        self._last_sent_fingerprint = fingerprint
        self._last_emit_ts = time.time()

    def _run_single(self):
        try:
            print("[SemanticProactiveWorker] evaluating change with highlight detector...")
            # Block other proactive flows until this one finishes
            with self.__class__._global_send_lock:
                cfg = load_config()
                proc = (cfg.get('processing') or {})
                proactive_cfg = (cfg.get('proactive') or {})
                rf = float(proc.get('video_resize_factor', 0.35))
                max_dim = max(600, int(1200 * min(1.0, max(0.25, rf))))
                before_to_send = downscale_image_for_upload(self.before_path, max_dim=max_dim)
                after_to_send = downscale_image_for_upload(self.after_path, max_dim=max_dim)

                base_threshold = float(proactive_cfg.get('min_change_percent', 1))
                # Randomize threshold between half and full value
                threshold = random.uniform(base_threshold * 0.5, base_threshold)

                pct = _percent_image_diff(before_to_send, after_to_send, resize_side=256)
            if pct < threshold:
                print("[SemanticProactiveWorker] change below threshold; skipping proactive message.")
                for ptmp, porig in ((before_to_send, self.before_path), (after_to_send, self.after_path)):
                    try:
                        if ptmp and ptmp != porig and os.path.exists(ptmp):
                            os.remove(ptmp)
                    except Exception:
                        pass
                return

            # Only log when we trigger a proactive send due to sufficient change
            print(f"[SemanticProactiveWorker] change detected: percent={pct:.4f} threshold={threshold}")
            fingerprint = self._fingerprint_file(after_to_send)
            min_interval = float(proactive_cfg.get('min_interval_sec', 15.0))
            if self._should_throttle_or_dedupe(fingerprint, min_interval):
                for ptmp, porig in ((before_to_send, self.before_path), (after_to_send, self.after_path)):
                    try:
                        if ptmp and ptmp != porig and os.path.exists(ptmp):
                            os.remove(ptmp)
                    except Exception:
                        pass
                return

            # Hold the in_progress flag across describe_change + send to avoid races
            with self._lock:
                if self._in_progress:
                    print("[SemanticProactiveWorker] competing send detected; aborting this detection.")
                    return
                self._in_progress = True

            try:
                # Highlight detection (no LLM)
                event = detect_highlight(before_to_send, after_to_send)

                score = float(event.get('score') or 0.0)
                score_th = float(proactive_cfg.get('highlight_score_threshold', 0.55))
                if score < score_th:
                    print(f"[SemanticProactiveWorker] highlight score {score:.2f} below threshold {score_th:.2f}; skipping.")
                    # cleanup downscaled temps
                    try:
                        if before_to_send and before_to_send != self.before_path and os.path.exists(before_to_send):
                            os.remove(before_to_send)
                    except Exception:
                        pass
                    try:
                        if after_to_send and after_to_send != self.after_path and os.path.exists(after_to_send):
                            os.remove(after_to_send)
                    except Exception:
                        pass
                    return

                # Build a concise change summary for the LLM to react to
                bbox = event.get('bbox') or []
                loc = ''
                if isinstance(bbox, list) and len(bbox) == 4:
                    loc = " (a region changed)"
                change_summary = (event.get('summary') or 'The screen updated.') + loc
                try:
                    # Prefer the already-downscaled after_to_send to ensure file existence during POST
                    response, emotion = send_semantic_proactive(change_summary, after_to_send or self.after_path)
                    print("[SemanticProactiveWorker] single-run proactive response ready (LLM)")
                    self._mark_sent(fingerprint)
                    self.response_ready.emit(response, emotion)
                except Exception as ex:
                    print(f"[SemanticProactiveWorker] error sending proactive: {ex}")
                finally:
                    # cleanup downscaled temps
                    try:
                        if before_to_send and before_to_send != self.before_path and os.path.exists(before_to_send):
                            os.remove(before_to_send)
                    except Exception:
                        pass
                    try:
                        if after_to_send and after_to_send != self.after_path and os.path.exists(after_to_send):
                            os.remove(after_to_send)
                    except Exception:
                        pass
            finally:
                with self._lock:
                    self._in_progress = False

        except Exception as e:
            import traceback as _tb
            print("[SemanticProactiveWorker] error:", e)
            self.error.emit(f"Error in semantic proactive worker: {e}\n{_tb.format_exc()}")
        finally:
            for p in [self.before_path, self.after_path]:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

    def _run_continuous(self):
        cfg = load_config()
        proactive_cfg = (cfg.get('proactive') or {})
        sample_interval = float(proactive_cfg.get('sample_interval_ms', 1000)) / 1000.0
        min_interval = float(proactive_cfg.get('min_interval_sec', 15.0))
        # Use a conservative default and clamp to avoid being too insensitive
        base_threshold_cfg = float((cfg.get('proactive') or {}).get('min_change_percent', 2.5))
        base_threshold = max(0.5, min(3.0, base_threshold_cfg))
        # Randomize threshold between half and full value (percent scale 0..100)
        threshold = random.uniform(base_threshold * 0.5, base_threshold)
        print(f"[SemanticProactiveWorker] [{time.strftime('%H:%M:%S')}] starting continuous monitoring loop ({int(sample_interval*1000)}ms interval)...")
        before_path = None
        consecutive_failures = 0
        try:
            while not self._stop_requested:
                try:
                    ss_before = take_screenshot(cfg.get('processing', {}).get('video_resize_factor', 0.35))
                    if not ss_before:
                        time.sleep(sample_interval)
                        continue
                    before_path, _, _ = ss_before
                    time.sleep(sample_interval)
                    ss_after = take_screenshot(cfg.get('processing', {}).get('video_resize_factor', 0.35))
                    if not ss_after:
                        try:
                            if before_path and os.path.exists(before_path):
                                os.remove(before_path)
                        except Exception:
                            pass
                        time.sleep(sample_interval)
                        before_path = None
                        continue
                    after_path, _, _ = ss_after
                    # Compute diff percent but avoid verbose logging unless we trigger
                    pct = _percent_image_diff(before_path, after_path, resize_side=256)
                    if pct < threshold:
                        for p in [before_path, after_path]:
                            _safe_remove(p)
                        before_path = None
                        time.sleep(sample_interval)
                        continue

                    rf = float(cfg.get('processing', {}).get('video_resize_factor', 0.35))
                    max_dim = max(600, int(1200 * min(1.0, max(0.25, rf))))
                    before_to_send = downscale_image_for_upload(before_path, max_dim=max_dim)
                    after_to_send = downscale_image_for_upload(after_path, max_dim=max_dim)

                    # Only log when we trigger a proactive send due to sufficient change
                    print(f"[SemanticProactiveWorker] change detected: percent={pct:.4f} threshold={threshold}")
                    fingerprint = self._fingerprint_file(after_to_send)
                    if self._should_throttle_or_dedupe(fingerprint, min_interval):
                        for ptmp, porig in ((before_to_send, before_path), (after_to_send, after_path)):
                            if ptmp and ptmp != porig:
                                _safe_remove(ptmp)
                        for p in [before_path, after_path]:
                            _safe_remove(p)
                        before_path = None
                        time.sleep(sample_interval)
                        continue

                    # Acquire send lock and keep it until after send to avoid races
                    with self._lock:
                        if self._in_progress:
                            print("[SemanticProactiveWorker] send in progress; skipping this iteration.")
                            for ptmp, porig in ((before_to_send, before_path), (after_to_send, after_path)):
                                if ptmp and ptmp != porig:
                                    _safe_remove(ptmp)
                            for p in [before_path, after_path]:
                                _safe_remove(p)
                            before_path = None
                            time.sleep(sample_interval)
                            continue
                        self._in_progress = True

                    # Global lock to prevent overlapping proactive sends from any source
                    with self.__class__._global_send_lock:
                        try:
                            # Highlight detection
                            event = detect_highlight(before_to_send, after_to_send)

                            score = float(event.get('score') or 0.0)
                            score_th = float(proactive_cfg.get('highlight_score_threshold', 0.55))
                            if score < score_th:
                                print(f"[SemanticProactiveWorker] highlight score {score:.2f} below threshold {score_th:.2f}; skipping.")
                                consecutive_failures += 1
                                # cleanup downscaled temps
                                for ptmp, porig in ((before_to_send, before_path), (after_to_send, after_path)):
                                    if ptmp and ptmp != porig:
                                        _safe_remove(ptmp)
                            else:
                                try:
                                    bbox = event.get('bbox') or []
                                    loc = ''
                                    if isinstance(bbox, list) and len(bbox) == 4:
                                        loc = " (a region changed)"
                                    change_summary = (event.get('summary') or 'The screen updated.') + loc
                                    # Prefer the already-downscaled after_to_send to ensure file existence during POST
                                    response, emotion = send_semantic_proactive(change_summary, after_to_send or after_path)
                                    print(f"[SemanticProactiveWorker] proactive response ready (LLM): {response!r}")
                                    self.response_ready.emit(response, emotion)
                                    self._mark_sent(fingerprint)
                                    consecutive_failures = 0
                                except Exception as ex:
                                    print(f"[SemanticProactiveWorker] error sending proactive: {ex}")
                                    consecutive_failures += 1
                                finally:
                                    # cleanup downscaled temps
                                    for ptmp, porig in ((before_to_send, before_path), (after_to_send, after_path)):
                                        if ptmp and ptmp != porig:
                                            _safe_remove(ptmp)
                        finally:
                            with self._lock:
                                self._in_progress = False

                    # cleanup originals
                    for p in [before_path, after_path]:
                        _safe_remove(p)
                    before_path = None

                    if consecutive_failures >= 3:
                        backoff = min(60, 5 * consecutive_failures)
                        print(f"[SemanticProactiveWorker] consecutive failures={consecutive_failures}; backing off {backoff}s")
                        time.sleep(backoff)
                        consecutive_failures = 0

                    time.sleep(sample_interval)
                except Exception as loop_ex:
                    print(f"[SemanticProactiveWorker] loop error: {loop_ex}")
                    time.sleep(sample_interval)
                    continue
        except Exception as e:
            import traceback as _tb
            print(f"[SemanticProactiveWorker] error: {e}")
            self.error.emit(f"Error in semantic proactive worker: {e}\n{_tb.format_exc()}")
        finally:
            print(f"[SemanticProactiveWorker] [{time.strftime('%H:%M:%S')}] monitoring loop stopped")

class CompletionSummaryWorker(QThread):
    summary_ready = pyqtSignal(str, object)
    error = pyqtSignal(str)

    def __init__(self, user_goal: str):
        super().__init__()
        self.user_goal = user_goal

    def run(self):
        try:
            print(f"[CompletionSummaryWorker] generating completion for: {self.user_goal!r}")
            text, emotion = generate_task_completion_summary(self.user_goal)
            print("[CompletionSummaryWorker] summary ready; chars =", len(text or ""))
            self.summary_ready.emit(text, emotion)
        except Exception as e:
            import traceback as _tb
            print("[CompletionSummaryWorker] error:", e)
            self.error.emit(f"Error in completion summary worker: {e}\n{_tb.format_exc()}")


class AgenticTaskWorker(QThread):
    finished = pyqtSignal(str, str)
    error = pyqtSignal(str)
    progress_update = pyqtSignal(str)
    ask_user_signal = pyqtSignal(str)

    def __init__(
        self,
        user_goal: str,
        initial_plan: List[Dict[str, Any]],
        desired_result: str,
        screenshot_path: str,
        width: int,
        height: int,
        interrupt_event,
        confirmation_message: str,
    ):
        super().__init__()
        self.user_goal = user_goal
        self.current_plan = deque(initial_plan)
        self.desired_result = desired_result
        self.interrupt_event = interrupt_event
        self.current_screenshot_path = screenshot_path
        self.confirmation_message = confirmation_message
        self.user_response_event = None
        self.user_response_text = ''
        self.width = width
        self.height = height

    def run(self):
        try:
            self.progress_update.emit(f"Starting task: {self.user_goal}")
            print(f"[AgenticTaskWorker] start: goal={self.user_goal!r}; desired={self.desired_result!r}; screenshot={self.current_screenshot_path}")
            last_action_description = f"I just told the user: '{self.confirmation_message}'. Now I am starting the task."
            is_finished = False
            while not is_finished and not self.interrupt_event.is_set():
                decision = get_next_agentic_step(self.user_goal, last_action_description, self.desired_result, self.current_screenshot_path)
                if not decision:
                    self.error.emit('Model failed to provide a decision. Stopping.')
                    break
                if decision.get('task_is_complete'):
                    self.progress_update.emit(f"LLM Reasoning: {decision.get('completion_analysis')}")
                    is_finished = True
                    break
                step = decision.get('next_action')
                if not step or not isinstance(step, dict):
                    self.progress_update.emit(f"LLM Reasoning: {decision.get('completion_analysis')}")
                    is_finished = True
                    break
                print(f"[AgenticTaskWorker] executing step: {step}")
                last_action_description = self._execute_action(step)
                time.sleep(1.5)
                if os.path.exists(self.current_screenshot_path):
                    try:
                        os.remove(self.current_screenshot_path)
                    except OSError:
                        pass
                # Use the configured downscale factor for screenshot capture
                from milkchan.desktop.utils.config import load_config as _load_cfg
                _cfg = _load_cfg()
                _rf = float((_cfg.get('processing') or {}).get('video_resize_factor', 0.35))
                from milkchan.desktop.utils.screenshot import take_screenshot as _shot
                ss = _shot(_rf)
                if not ss:
                    raise RuntimeError('Failed to take a new screenshot.')
                self.current_screenshot_path, self.width, self.height = ss
                print(f"[AgenticTaskWorker] captured new screenshot: {self.current_screenshot_path} ({self.width}x{self.height})")
            status = 'interrupted' if self.interrupt_event.is_set() else 'success'
            print(f"[AgenticTaskWorker] finished with status={status}")
            self.finished.emit(status, self.user_goal)
        except Exception as e:
            tb = traceback.format_exc()
            print("[AgenticTaskWorker] error:", e)
            self.error.emit(f"Error during agentic task: {e}\n{tb}")
        finally:
            try:
                if self.current_screenshot_path and os.path.exists(self.current_screenshot_path):
                    os.remove(self.current_screenshot_path)
            except Exception:
                pass

    def _execute_action(self, step: Dict[str, Any]) -> str:
        import pyautogui
        action = step.get('action')
        if action == 'ask_user':
            q = step.get('question', 'I have a question.')
            self.progress_update.emit(f"Waiting for user input: {q}")
            print(f"[AgenticTaskWorker] ask_user: {q}")
            self.user_response_event = __import__('threading').Event()
            self.ask_user_signal.emit(q)
            self.user_response_event.wait()
            return f"I asked the user '{q}' and they responded with '{self.user_response_text}'."
        if action == 'find_and_click':
            object_name = step.get('object_name')
            if not object_name:
                return "Missing object_name."
            from milkchan.desktop.services.ai_client import grounding_bbox
            print(f"[AgenticTaskWorker] grounding for: {object_name!r}")
            box = grounding_bbox(object_name, self.current_screenshot_path, self.width, self.height)
            if box:
                y_min, x_min, y_max, x_max = box
                cx = (x_min + x_max) // 2
                cy = (y_min + y_max) // 2
                pyautogui.click(cx, cy)
                print(f"[AgenticTaskWorker] clicked at ({cx},{cy}) on '{object_name}'")
                return f"I clicked on '{object_name}'."
            print(f"[AgenticTaskWorker] could not find '{object_name}'")
            return f"I tried to click on '{object_name}' but could not find it."
        if action == 'type':
            val = step.get('value', '')
            pyautogui.typewrite(val, interval=step.get('interval', 0.05))
            print(f"[AgenticTaskWorker] typed: {val[:40]!r}")
            return f"I typed '{val[:20]}...'."
        if action == 'press':
            key = step.get('key') or ''
            pyautogui.press('win' if key.lower() == 'windows' else key)
            print(f"[AgenticTaskWorker] pressed key: {key!r}")
            return f"I pressed the '{key}'."
        if action == 'hotkey':
            keys = step.get('keys') or []
            if isinstance(keys, list) and keys:
                pyautogui.hotkey(*keys)
                print(f"[AgenticTaskWorker] hotkey: {' + '.join(keys)}")
                return f"I used the hotkey '{' + '.join(keys)}'."
        if action == 'wait':
            import time as _t
            d = step.get('duration', 1.0)
            print(f"[AgenticTaskWorker] waiting {d}s")
            _t.sleep(d)
            return f"I waited for {d} seconds."
        print(f"[AgenticTaskWorker] unknown action: {action!r}")
        return f"Unknown action '{action}'."