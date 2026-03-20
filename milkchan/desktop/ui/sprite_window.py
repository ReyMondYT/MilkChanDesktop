import os
import random
import sys
import time


from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QAbstractNativeEventFilter, QCoreApplication, pyqtSlot
from PyQt5.QtWidgets import QMainWindow, QLabel, QMenu, QMessageBox, QApplication
from PyQt5.QtGui import QImage, QPixmap

from milkchan.desktop.ui.chat_overlay import ChatOverlay
from milkchan.desktop.ui.settings_window import SettingsWindow
from milkchan.core.config import load_config, save_config
from milkchan.desktop.utils.recorder import BackgroundRecorder
from milkchan.desktop.utils.sprites import (
    load_sprite_mappings,
    build_sprite_tree_string,
    add_expressions,
    normalize_img,
)
from milkchan.desktop.services import memory_client
from milkchan.desktop.agents.agent_workers import (
    SaveAndSendWorker,
    ProactiveMessageWorker,
    CompletionSummaryWorker,
    AgenticTaskWorker,
    SemanticProactiveWorker,
)
from milkchan.desktop.utils.screen_watcher import ScreenWatcher
from milkchan.desktop.services.ipc_server import get_ipc_server
from milkchan.bootstrap import get_assets_dir, is_cache_valid

ASSETS_DIR = str(get_assets_dir())
SPRITES_DIR = os.path.join(ASSETS_DIR, 'sprites')


# Windows global hotkey support: Register F8 and catch WM_HOTKEY to toggle visibility even when hidden
if sys.platform.startswith('win'):
    import ctypes
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    MOD_NOREPEAT = 0x4000
    VK_F8 = 0x77
    HOTKEY_ID_F8 = 1

    class _WinHotkeyFilter(QAbstractNativeEventFilter):
        def __init__(self, on_f8_callback):
            super().__init__()
            self._on_f8 = on_f8_callback

        def nativeEventFilter(self, eventType, message):
            try:
                if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG", "windows_generic_MSG", "windows_dispatcher_MSG"):
                    # message is a pointer to MSG structure
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID_F8:
                        if callable(self._on_f8):
                            self._on_f8()
                        # Mark handled to prevent further propagation
                        return True, 0
            except Exception:
                # Never crash on event filter errors
                pass
            return False, 0

class SpriteWindow(QMainWindow):
    toggle_visibility_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        
        
        self.config = load_config()
        self._sprite_cache = {}
        # Cache final QPixmaps for a given state to avoid heavy recomposition every tick
        self._composite_cache = {}

        self.pyautogui_worker = None
        self.completion_worker = None
        self.is_task_running = False
        self.task_interrupt_event = None
        self.is_answering_agent = False
        self.waiting_agent_worker = None

        # Track overlay pause state (toggled via F7)
        self.overlay_paused = False

        # Window flags and attributes
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Start visible by default; mouse events initially pass through until overlay is shown
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Core widgets
        self.label = QLabel(self)
        self.setCentralWidget(self.label)

        # Sprite state
        self.current_pose = 'arms_crossed'
        self.current_mood = 'neutral'
        self.current_variation = 1
        self.current_expressions = []

        # Anim state
        self.is_speaking = False
        self.mouth_state = 0
        self.is_blinking = False
        self.thinking = False

        self.mouth_timer = QTimer(self)
        self.mouth_timer.timeout.connect(self.animate_mouth)

        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.start_blink)
        self.blink_end_timer = QTimer(self)
        self.blink_end_timer.timeout.connect(self.end_blink)
        self.blink_end_timer.setSingleShot(True)

        # Create overlay, recorder, preload sprites, timers, etc. BEFORE registering hotkey
        self._preload_sprites()

        self.chat_overlay = ChatOverlay(self, self.config)

        self.background_recorder = BackgroundRecorder(config=self.config)
        # Apply capture mode (vision_mode: 'video' or 'image')
        proc_cfg = (self.config.get('processing') or {})
        vision_mode = proc_cfg.get('vision_mode') or ('video' if proc_cfg.get('vision_enabled', True) else 'image')
        self.background_recorder.processing_config = proc_cfg
        self.background_recorder.video_resize_factor = proc_cfg.get('video_resize_factor', 1.0)
        if vision_mode == 'video':
            self.background_recorder.vision_enabled = True
            self.background_recorder.audio_enabled = True
            self.background_recorder.start_recording()
        else:
            self.background_recorder.vision_enabled = False
            self.background_recorder.audio_enabled = False
            # In image mode, screenshots provide context instead of live recording

        # Timers and workers
        self.proactive_message_timer = QTimer(self)
        self.proactive_message_timer.setSingleShot(True)
        self.proactive_message_timer.timeout.connect(self.send_proactive_message)
        self.proactive_worker = None

        # Connect signal
        self.toggle_visibility_signal.connect(self.toggle_visibility)

        # Register global hotkey (Windows only) AFTER everything is initialized
        self._hotkey_filter = None
        if sys.platform.startswith('win'):
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = int(self.winId())
                # MOD_NOREPEAT prevents auto-repeat; 0 modifier means F8 alone
                if user32.RegisterHotKey(hwnd, HOTKEY_ID_F8, MOD_NOREPEAT, VK_F8):
                    self._hotkey_filter = _WinHotkeyFilter(self._on_global_f8)
                    QCoreApplication.instance().installNativeEventFilter(self._hotkey_filter)
                    print("[SpriteWindow] Registered global F8 hotkey.")
                else:
                    print("[SpriteWindow] Failed to register global F8 hotkey.")
            except Exception as e:
                print("[SpriteWindow] Exception while registering F8 hotkey:", e)

        # ScreenWatcher disabled for proactive flows; we rely on random timer instead
        self.screen_watcher = None

        # Finish init
        self.update_sprite()
        self.update_position()
        # Debounce toggles in case of double events
        self._last_toggle_ts = 0.0

        self.schedule_next_blink()
        self.schedule_proactive_message()

        # Start IPC server for terminal chat
        ipc_server = get_ipc_server()
        ipc_server.set_sprite_window(self)
        ipc_server.start()
    
    def __del__(self):
        try:
            get_ipc_server().stop()
        except Exception:
            pass
        try:
            self.background_recorder.stop_recording()
        except Exception:
            # Debounce: ignore toggles fired within 200ms
            now = time.time()
            if (now - getattr(self, '_last_toggle_ts', 0.0)) < 0.2:
                return
            self._last_toggle_ts = now

            pass

    # Called from native event filter on WM_HOTKEY(F8)
    def _on_global_f8(self):
        try:
            self.toggle_visibility_signal.emit()
        except Exception as e:
            print("[SpriteWindow] _on_global_f8 error:", e)

    def _preload_sprites(self):
        # Get resolution scale from config
        resolution_scale = self.config.get('sprite_resolution_scale', 1.0)
        self._resolution_scale = resolution_scale
        
        # Load sprites with the correct scale
        from milkchan.desktop.utils.sprites import load_sprites_with_scale, BASE_WIDTH, BASE_HEIGHT
        cache = load_sprites_with_scale(resolution_scale)
        
        if cache and 'sprites' in cache and 'mappings' in cache:
            print(f'Loading sprites from cache (scale={resolution_scale})...')
            self._sprite_cache = cache['sprites']
            self.expressions_dict = cache['mappings']
            self.AVAILABLE_SPRITES_TREE = build_sprite_tree_string(self.expressions_dict)
            print(f'Sprite cache loaded ({len(self._sprite_cache)} sprites)')
            return
        
        # Fallback: load from disk (slower)
        print('Caching sprites...')
        self.expressions_dict = load_sprite_mappings()
        # Use uniform scaling
        from milkchan.desktop.utils.sprites import ORIG_WIDTH, ORIG_HEIGHT, UNIFORM_SCALE
        scale = UNIFORM_SCALE * resolution_scale
        display_width = int(ORIG_WIDTH * scale)
        display_height = int(ORIG_HEIGHT * scale)
        # Precache base sprite images as numpy arrays for fast composition
        for pose, moods in self.expressions_dict.items():
            for mood, files in moods.items():
                for filename in files:
                    full_path = os.path.join(SPRITES_DIR, pose, mood, f"{filename}.png")
                    if os.path.exists(full_path):
                        try:
                            from PIL import Image
                            import numpy as np
                            img = Image.open(full_path).convert('RGBA')
                            # Resize using NEAREST for pixel art (preserves sharp edges)
                            img = img.resize((display_width, display_height), Image.Resampling.NEAREST)
                            cache_key = f"{pose}_{mood}_{filename}"
                            self._sprite_cache[cache_key] = np.array(img)
                        except Exception as e:
                            print(f"Could not cache sprite: {full_path}. Error: {e}")
        print('Sprite caching complete.')
        self.AVAILABLE_SPRITES_TREE = build_sprite_tree_string(self.expressions_dict)

    def reload_sprites_with_scale(self, resolution_scale: float):
        """Reload sprites with new resolution scale"""
        print(f"[SpriteWindow] Reloading sprites with scale {resolution_scale}...")
        self._resolution_scale = resolution_scale
        
        from milkchan.desktop.utils.sprites import load_sprites_with_scale
        cache = load_sprites_with_scale(resolution_scale)
        
        if cache and 'sprites' in cache:
            self._sprite_cache = cache['sprites']
            self.expressions_dict = cache.get('mappings', self.expressions_dict)
            self._composite_cache.clear()
            self.update_sprite()
            print(f'Sprites reloaded ({len(self._sprite_cache)} sprites)')

    def invalidate_composite_cache(self):
        self._composite_cache.clear()

    def create_save_send_worker(self, text: str):
        worker = SaveAndSendWorker(self.background_recorder, text)
        worker.response_ready.connect(self.chat_overlay.handle_response)
        worker.error.connect(self.chat_overlay.handle_error)
        
        return worker

    def handle_semantic_proactive(self, response: str, emotion: dict):
        print(f"[SpriteWindow] Proactive message received: {response!r}")
        if isinstance(emotion, dict) and isinstance(emotion.get('emotion'), list) and len(emotion['emotion']) >= 3:
            self.update_sprite_emotion(emotion['emotion'])
        # Optionally display in overlay
        self.chat_overlay.handle_response(response, emotion)


    def toggle_visibility(self):
        # Toggle assistant visibility and pause/resume background processes without reinitializing
        if self.is_task_running:
            self.interrupt_current_task()
            return
        if self.isVisible():
            print('Hiding window and pausing background processes...')
            self.hide()
            try:
                self.background_recorder.stop_recording()
            except Exception:
                pass
            self.blink_timer.stop()
            self.proactive_message_timer.stop()
            self.stop_speech_animation()
            if self.screen_watcher:
                self.screen_watcher.set_paused(True)
            if self.chat_overlay.isVisible():
                self.chat_overlay.hide()
        else:
            print('Showing window and resuming background processes...')
            self.show()
            proc_cfg = (self.config.get('processing') or {})
            vision_mode = proc_cfg.get('vision_mode') or ('video' if proc_cfg.get('vision_enabled', True) else 'image')
            if vision_mode == 'video' and not getattr(self.background_recorder, 'recording', False):
                self.background_recorder.start_recording()
            if self.screen_watcher:
                self.screen_watcher.set_paused(False)
                # Update ignore region on show
                self._update_watcher_ignore_region()
            self.schedule_next_blink()
            self.schedule_proactive_message()

    def _compose_pixmap_key(self, base_key: str, active_exps, scale_factor: float) -> str:
        uniq = sorted(set(active_exps))
        return f"{base_key}__sf{int(scale_factor*100)}__exp{'|'.join(uniq)}"

    def update_sprite(self, after_blink: bool = False):
        if after_blink:
            max_var = 3 if self.current_mood == 'neutral' else 2
            self.current_variation = random.randint(1, max_var)

        scale_factor = self.config.get('scale_factor', 100) / 100.0
        base_key = f"{self.current_pose}_{self.current_mood}_{self.current_mood}_{self.current_variation}"
        base_img = self._sprite_cache.get(base_key)

        if base_img is None:
            from PyQt5.QtGui import QPainter, QColor
            pixmap = QPixmap(260, 290)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(QColor('#FF66AA'))
            painter.drawRect(0, 0, 259, 289)
            painter.end()
            self.label.setPixmap(pixmap)
            self.resize(pixmap.size())
            return

        active_exps = self.current_expressions[:]
        if self.is_speaking:
            mouth_exp = 'mouth_full' if self.mouth_state == 2 else 'mouth_half'
            active_exps.append(mouth_exp)
        if self.is_blinking:
            active_exps.append('eyes_closed')
        if self.thinking:
            active_exps.append('eyes_half')

        cache_key = self._compose_pixmap_key(base_key, active_exps, scale_factor)
        pixmap = self._composite_cache.get(cache_key)

        if pixmap is None:
            expression_imgs = []
            for exp in active_exps:
                exp_key = f"{self.current_pose}_{self.current_mood}_{self.current_mood}_{exp}"
                if exp_key in self._sprite_cache:
                    expression_imgs.append(self._sprite_cache[exp_key])

            blended = add_expressions(base_img, expression_imgs) if expression_imgs else base_img
            resolution_scale = getattr(self, '_resolution_scale', 1.0)
            normalized = normalize_img(blended, scale_factor, resolution_scale)
            h, w, c = normalized.shape
            q_img = QImage(normalized.tobytes(), w, h, c * w, QImage.Format_RGBA8888)
            pixmap = QPixmap.fromImage(q_img)
            self._composite_cache[cache_key] = pixmap

        self.label.setPixmap(pixmap)
        if self.size() != pixmap.size():
            self.resize(pixmap.size())
            self.chat_overlay.update_scale(self.config.get('scale_factor', 100))
            self.update_position()

    def schedule_proactive_message(self):
        # Always schedule random proactive pings (video-describe tail)
        self.proactive_message_timer.stop()
        if getattr(self, 'overlay_paused', False):
            return
        import random as _r
        # Random interval: 10s .. 120s
        interval_ms = _r.randint(10_000, 120_000)
        print(f"[SpriteWindow] scheduling proactive in {interval_ms/1000:.1f}s")
        self.proactive_message_timer.start(interval_ms)

    def send_proactive_message(self):
        print("[SpriteWindow] proactive timer fired")
        # Skip if overlay is paused
        if getattr(self, 'overlay_paused', False):
            print("[SpriteWindow] proactive skipped: overlay_paused")
            self.schedule_proactive_message()
            return
        if self.chat_overlay.user_input.isActiveWindow():
            print("[SpriteWindow] proactive skipped: user typing")
            self.schedule_proactive_message()
            return
        # Skip if TUI terminal is active
        from milkchan.desktop.services.ipc_server import get_ipc_server
        ipc = get_ipc_server()
        if ipc.is_tui_active():
            print("[SpriteWindow] proactive skipped: TUI active")
            self.schedule_proactive_message()
            return

        self.thinking = True
        self.update_sprite()
        self.proactive_worker = ProactiveMessageWorker(self.background_recorder)
        self.proactive_worker.response_ready.connect(self.handle_proactive_response)
        self.proactive_worker.error.connect(self.chat_overlay.handle_error)
        self.proactive_worker.start()

    def on_semantic_screen_change(self, payload: dict):
        # Ignore screen change events entirely; cleanup temp files if any
        for p in [payload.get('before_path'), payload.get('after_path')]:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        return

    def handle_proactive_response(self, response: str, emotion: dict):
        # Apply provided emotion (from proactive chat) once here since ChatOverlay ignores final emotion payloads
        try:
            if isinstance(emotion, dict) and isinstance(emotion.get('emotion'), list) and len(emotion['emotion']) >= 3:
                self.update_sprite_emotion(emotion['emotion'])
        except Exception:
            pass
        self.chat_overlay.handle_response(response, emotion)
        self.schedule_proactive_message()

    @pyqtSlot()
    def _apply_pending_emotion(self):
        """Apply pending emotion from IPC call (thread-safe)"""
        emotion = getattr(self, '_pending_emotion', None)
        if emotion:
            self.update_sprite_emotion(emotion)
            self._pending_emotion = None

    def update_sprite_emotion(self, emotion_data: list):
        # Validate and coerce emotion to the nearest available sprite
        try:
            if not isinstance(emotion_data, list) or len(emotion_data) < 3:
                return
            pose_in, mood_in, var_in = emotion_data[:3]
            exps_in = [str(e) for e in emotion_data[3:]]

            expressions = self.expressions_dict or {}
            # Resolve pose
            pose = pose_in if pose_in in expressions else None
            if not pose:
                # Try simple pose synonyms
                p = str(pose_in).replace('-', ' ').replace('_', ' ').lower()
                pose_aliases = {
                    'arms crossed': 'arms_crossed', 'crossed': 'arms_crossed', 'crossed arms': 'arms_crossed',
                    'arms down': 'arms_down', 'down': 'arms_down',
                    'one arm': 'one_arm', 'one-armed': 'one_arm', 'one handed': 'one_arm', 'one-handed': 'one_arm'
                }
                cand = pose_aliases.get(p)
                if cand in expressions:
                    pose = cand
            if not pose:
                pose = next(iter(expressions.keys()), None)
            if not pose:
                return
            # Resolve mood
            moods = expressions.get(pose, {})
            mood = mood_in if mood_in in moods else None
            if not mood:
                m = str(mood_in).lower()
                mood_syn = {
                    'nervous': 'nerv', 'nerv': 'nerv',
                    'angry': 'mad', 'mad': 'mad', 'annoyed': 'mad', 'frustrated': 'mad',
                    'confused': 'conf', 'conf': 'conf',
                    'curious': 'neutral',
                    'smiling': 'smile', 'smile': 'smile', 'happy': 'smile', 'joy': 'smile',
                    'sad': 'sad', 'upset': 'sad',
                    'neutral': 'neutral', 'calm': 'neutral'
                }
                mapped = mood_syn.get(m, m)
                if mapped in moods:
                    mood = mapped
            if not mood:
                mood = 'neutral' if 'neutral' in moods else (next(iter(moods.keys()), None))
            if not mood:
                return
            # Determine available variations and expressions for this mood
            filenames = moods.get(mood, [])
            # variation numbers are filenames like mood_1, mood_2, ...; expressions are non-numeric suffixes
            variations = sorted({int(f[len(mood)+1:]) for f in filenames if f.startswith(mood + '_') and f[len(mood)+1:].isdigit()})
            valid_exps = {f[len(mood)+1:] for f in filenames if f.startswith(mood + '_') and not f[len(mood)+1:].isdigit()}
            # Clamp/choose variation
            try:
                v = int(var_in)
            except Exception:
                v = None
            if not variations:
                variation = 1
            else:
                if v in variations:
                    variation = v
                else:
                    # pick closest variation number
                    variation = min(variations, key=lambda x: abs((v if isinstance(v, int) else variations[0]) - x))
            # Filter expressions: drop mouth_* (managed by animation) and keep only valid ones
            cleaned_exps = []
            for e in exps_in:
                e = e.strip()
                if not e or e.startswith('mouth_'):
                    continue
                if e in valid_exps:
                    cleaned_exps.append(e)

            self.current_pose = pose
            self.current_mood = mood
            self.current_variation = variation
            self.current_expressions = cleaned_exps
            self.invalidate_composite_cache()
            self.update_sprite()
        except Exception:
            # Never crash UI on malformed emotion
            pass

    def animate_mouth(self):
        if not self.is_speaking:
            self.mouth_timer.stop()
            self.mouth_state = 0
            return
        self.mouth_state = 2 if self.mouth_state == 0 else 0
        self.update_sprite()

    @pyqtSlot()
    def start_speech_animation(self):
        self.is_speaking = True
        interval = max(100, int(self.chat_overlay.char_delay * 2.0))
        self.mouth_timer.start(interval)
        # Play narration audio if available
        try:
            if hasattr(self.chat_overlay, 'audio_player'):
                self.chat_overlay.audio_player.stop()
                self.chat_overlay.audio_player.play()
        except Exception:
            pass

    @pyqtSlot()
    def stop_speech_animation(self):
        self.mouth_timer.stop()
        self.is_speaking = False
        self.mouth_state = 0
        self.update_sprite()
        # Stop narration audio
        try:
            if hasattr(self.chat_overlay, 'audio_player'):
                self.chat_overlay.audio_player.stop()
        except Exception:
            pass

    def start_blink(self):
        self.is_blinking = True
        self.update_sprite()
        self.blink_end_timer.start(150)
        self.blink_timer.stop()

    def end_blink(self):
        self.is_blinking = False
        self.update_sprite(after_blink=True)
        self.schedule_next_blink()

    def schedule_next_blink(self):
        self.blink_timer.start(random.randint(2000, 8000))

    def contextMenuEvent(self, event):
        was_recording = self.background_recorder.recording
        if was_recording:
            self.background_recorder.stop_recording()

        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        menu = QMenu(self)
        menu.addAction('Settings', self.open_settings)
        menu.addAction('Check for Updates', self.check_for_updates)
        menu.addAction('Clear History', self.clear_history)
        menu.addAction('Exit', QApplication.quit)
        menu.exec_(self.mapToGlobal(event.pos()))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Only resume if in video mode
        proc_cfg = (self.config.get('processing') or {})
        vision_mode = proc_cfg.get('vision_mode') or ('video' if proc_cfg.get('vision_enabled', True) else 'image')
        if was_recording and vision_mode == 'video':
            self.background_recorder.start_recording()

    def open_settings(self):
        was_recording = self.background_recorder.recording
        if was_recording:
            self.background_recorder.stop_recording()

        current_persona = memory_client.get_item('persona', 'personality') or ''
        dlg = SettingsWindow(self, self.config, current_persona)

        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        if dlg.exec_() == dlg.Accepted:
            old_scale = int(self.config.get('scale_factor', 100))
            old_sprite_scale = float(self.config.get('sprite_resolution_scale', 1.0))
            new_config, new_persona = dlg.results()
            if new_config:
                # Update self.config with new values
                self.config.update(new_config)
                cfg_changed, proc_changed = self._apply_config_updates(new_config)
                
                # Save to file using Config object
                from milkchan.core.config import Config
                config_obj = Config()
                config_obj.update(new_config)
                
                # Reload AI client config cache
                from milkchan.desktop.services import ai_client
                ai_client.reload_config()
                
                # Check if sprite resolution scale changed
                new_sprite_scale = float(new_config.get('sprite_resolution_scale', 1.0))
                if abs(new_sprite_scale - old_sprite_scale) > 0.01:
                    self.reload_sprites_with_scale(new_sprite_scale)
                
                # Update UI
                self.chat_overlay.base_font_size = self.config.get('font_size', 6)
                self.chat_overlay.char_delay = self.config.get('char_delay_ms', 50)
                self.chat_overlay.update_scale(self.config.get('scale_factor', 100))
                if int(self.config.get('scale_factor', 100)) != old_scale:
                    self.invalidate_composite_cache()
                self.update_sprite()
                self.update_position()

            if new_persona is not None and new_persona != current_persona:
                memory_client.set_item('persona', 'personality', new_persona)

        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # Apply recorder settings from updated config
        proc_cfg = self.config.get('processing', {}) or {}
        self.background_recorder.config = self.config
        self.background_recorder.processing_config = proc_cfg
        vision_mode = proc_cfg.get('vision_mode') or ('video' if proc_cfg.get('vision_enabled', True) else 'image')
        self.background_recorder.video_resize_factor = proc_cfg.get('video_resize_factor', 1.0)

        if vision_mode == 'video':
            self.background_recorder.vision_enabled = True
            self.background_recorder.audio_enabled = True
            self.background_recorder.start_recording()
        else:
            self.background_recorder.vision_enabled = False
            self.background_recorder.audio_enabled = False
            self.background_recorder.stop_recording()
            # Image mode relies on screenshots; ensure setting is on for legacy behavior
            proc_cfg['screenshot_on_disabled_vision'] = bool(proc_cfg.get('screenshot_on_disabled_vision', True))

        # Update watcher with latest config
        if self.screen_watcher:
            try:
                self.screen_watcher.update_config(self.config)
                self._update_watcher_ignore_region()
            except Exception:
                pass

    def _apply_config_updates(self, new_cfg: dict):
        cfg_changed = False
        proc_changed = False

        def diff(a, b): return a != b

        for k in ['scale_factor', 'font_size', 'char_delay_ms', 'username']:
            if k in new_cfg and diff(self.config.get(k), new_cfg.get(k)):
                self.config[k] = new_cfg[k]
                cfg_changed = True

        self.config.setdefault('position', {})
        new_pos = new_cfg.get('position', {}) or {}
        for k in ['x_offset', 'y_offset']:
            if k in new_pos and diff(self.config['position'].get(k), new_pos.get(k)):
                self.config['position'][k] = new_pos[k]
                cfg_changed = True

        # Processing updates: prefer vision_mode; keep other keys
        self.config.setdefault('processing', {})
        new_proc = new_cfg.get('processing', {}) or {}

        # New keys and core fields
        for k in ['vision_mode', 'video_resize_factor', 'screenshot_on_disabled_vision']:
            if k in new_proc and diff(self.config['processing'].get(k), new_proc.get(k)):
                self.config['processing'][k] = new_proc[k]
                proc_changed = True

        # Legacy mapping: vision_enabled/audio_enabled -> vision_mode
        if 'vision_enabled' in new_proc:
            mapped_mode = 'video' if new_proc.get('vision_enabled') else 'image'
            if diff(self.config['processing'].get('vision_mode'), mapped_mode):
                self.config['processing']['vision_mode'] = mapped_mode
                proc_changed = True

        if new_proc.get('audio_enabled') is False:
            if diff(self.config['processing'].get('vision_mode'), 'image'):
                self.config['processing']['vision_mode'] = 'image'
                proc_changed = True

        # Preserve legacy flags too (for components that still read them)
        for legacy_k in ['vision_enabled', 'audio_enabled']:
            if legacy_k in new_proc and diff(self.config['processing'].get(legacy_k), new_proc.get(legacy_k)):
                self.config['processing'][legacy_k] = new_proc[legacy_k]
                proc_changed = True

        return cfg_changed, proc_changed

    def clear_history(self):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.chat_overlay.position_overlay()
        self.chat_overlay.show()
        self.chat_overlay.user_input.hide()
        self.chat_overlay.ai_response.show()
        memory_client.update_history([])
        
        # Notify TUI if active
        if hasattr(self, 'ipc_server') and self.ipc_server:
            self.ipc_server.notify_tui_clear_history()
        
        try:
            self.update_sprite_emotion(['arms_down', 'smile', 1])
        except Exception:
            pass
        self.chat_overlay.handle_response('History cleared!', {'emotion': ['arms_down', 'smile', 1]})

    def check_for_updates(self):
        """Check for updates from GitHub repository"""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        
        from milkchan.core.updater import check_updates_sync, format_update_message
        
        # Show checking message
        self.chat_overlay.handle_response('Checking for updates...', {'emotion': ['arms_down', 'smile', 1]})
        QApplication.processEvents()
        
        # Check for updates
        update_info = check_updates_sync(force=True)
        
        if update_info is None:
            QMessageBox.warning(self, 'Update Check Failed', 
                              'Failed to check for updates.\n\nMake sure you have:\n'
                              '1. GitHub CLI (gh) installed\n'
                              '2. Access to the private repository\n'
                              '3. Internet connection')
        elif update_info.available:
            # Update available - show dialog
            message = format_update_message(update_info)
            reply = QMessageBox.question(
                self, 
                'Update Available',
                message + '\n\nWould you like to apply this update now?\n'
                         '(This will restart the application)',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                from milkchan.core.updater import get_updater
                updater = get_updater()
                
                self.chat_overlay.handle_response('Applying update...', {'emotion': ['arms_down', 'smile', 1]})
                QApplication.processEvents()
                
                if updater.apply_update():
                    QMessageBox.information(
                        self,
                        'Update Applied',
                        'Update applied successfully!\n\nThe application will now restart.'
                    )
                    
                    # Restart the application
                    import subprocess
                    subprocess.Popen([sys.executable, '-m', 'milkchan.main'])
                    QApplication.quit()
                else:
                    QMessageBox.critical(
                        self,
                        'Update Failed',
                        'Failed to apply update.\n\nPlease check the logs for details.'
                    )
            else:
                self.chat_overlay.handle_response('Update postponed.', {'emotion': ['arms_down', 'smile', 1]})
        else:
            # No updates available
            QMessageBox.information(
                self,
                'No Updates',
                f'You are already on the latest version!\n\n'
                f'Commit: {update_info.current_sha[:7]}\n'
                f'Date: {update_info.commit_date[:10]}'
            )
            self.chat_overlay.handle_response('You are up to date!', {'emotion': ['arms_down', 'smile', 1]})
        
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def update_position(self):
        from PyQt5.QtWidgets import QDesktopWidget
        screen = QDesktopWidget().screenGeometry()
        x_off = int(self.config['position'].get('x_offset', 0))
        y_off = int(self.config['position'].get('y_offset', 0))
        # Allow offsets to go negative or positive up to the screen size
        x_off = max(-screen.width(), min(screen.width(), x_off))
        y_off = max(-screen.height(), min(screen.height(), y_off))
        x = screen.width() - self.width() + x_off
        y = screen.height() - self.height() + y_off
        self.move(x, y)
        # Keep watcher ignoring the overlay region
        self._update_watcher_ignore_region()

    def _update_watcher_ignore_region(self):
        try:
            if self.screen_watcher:
                g = self.geometry()
                self.screen_watcher.update_ignore_region(g.x(), g.y(), g.width(), g.height())
        except Exception:
            pass

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F7:
            # Toggle overlay and pause/resume background processes
            if self.chat_overlay.isVisible():
                # Hide and pause
                self.chat_overlay.hide_overlay()
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self.blink_timer.stop()
                self.stop_speech_animation()
            else:
                # Show and resume
                self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                self.chat_overlay.position_overlay()
                self.chat_overlay.show_overlay()
                
        elif event.key() == Qt.Key_F8:
            # On Windows, global WM_HOTKEY already handles F8; avoid double toggle
            if not sys.platform.startswith('win'):
                # Debounce in case key repeats
                now = time.time()
                if (now - getattr(self, '_last_toggle_ts', 0.0)) >= 0.2:
                    self._last_toggle_ts = now
                    self.toggle_visibility()
            else:
                event.ignore()

        else:
            super().keyPressEvent(event)