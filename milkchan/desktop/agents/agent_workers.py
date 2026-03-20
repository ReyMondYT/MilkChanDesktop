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
                                    result = send_semantic_proactive(change_summary, after_to_send or after_path)
                                    if result.get('error'):
                                        print(f"[SemanticProactiveWorker] error: {result['error'].get('type')} - {result['error'].get('message')}")
                                    else:
                                        print(f"[SemanticProactiveWorker] proactive response ready (LLM): {result.get('response', '')!r}")
                                        self.response_ready.emit(result.get('response', ''), result.get('emotion'))
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
                        except Exception as e:
                            print(f"[SemanticProactiveWorker] error in global lock: {e}")
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