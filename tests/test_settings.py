from milkchan.desktop.ui.settings_window import APITab, ToolsTab, VisionTab

BRAIN = {"base_url": "", "model": "m1", "thinking_mode": "tokens", "thinking_tokens": 8192,
         "vision": True, "request_budget": 800 * 1024, "api_key_set": True, "web_search_key_set": False,
         "defaults": {"base_url": "https://default.invalid/v1", "model": "default-model"}}


def test_brain_settings_round_trip_and_secrets_are_write_only(qapp, monkeypatch):
    monkeypatch.setattr(APITab, "_fetch_models_async", lambda self: None)
    api, vision, tools = APITab(BRAIN["defaults"]), VisionTab({}), ToolsTab()
    cfg = {"updates": {"github_token": "ghp"}, "processing": {"support_images": True}}
    api.load_values(cfg, BRAIN)
    vision.load_values(cfg, BRAIN)
    tools.load_values(BRAIN)
    assert api.api_key_edit.text() == "" and "Saved" in api.api_key_edit.placeholderText()
    assert "default.invalid" in api.base_url_edit.placeholderText()
    assert api.thinking_tokens_spin.isEnabled() and api.thinking_tokens_spin.value() == 8192

    api.thinking_mode_combo.setCurrentIndex(api.thinking_mode_combo.findData("high"))
    vision.model_vision_chk.setChecked(False)
    changes, saved = {}, {"processing": {}}
    api.save_values(saved, changes)
    vision.save_values(saved, changes)
    tools.save_values(changes)
    assert "api_key" not in changes and "web_search_key" not in changes
    assert changes["thinking_mode"] == "high" and changes["model"] == "m1" and changes["vision"] is False
    assert saved["updates"]["github_token"] == "ghp" and saved["processing"]["support_images"] is True

    api.api_key_edit.setText(" sk-new ")
    tools.web_search_token_edit.setText("brave")
    api.save_values(saved, changes)
    tools.save_values(changes)
    assert changes["api_key"] == "sk-new" and changes["web_search_key"] == "brave"
