#!/usr/bin/env python3
"""Native Qt/Quickshell renders of the actual panel with synthetic, offline data.

Development-only: requires a running Wayland desktop, Quickshell, Omarchy and
ImageMagick. Never starts the collector, reads credentials or modifies live usage data.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]


def render(light=False, output=ROOT / "preview.png"):
    base = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="konousage-preview-", dir=base) as directory:
        work = Path(directory)
        plugin = work / "Demo"
        plugin.mkdir()
        for name in ("Panel.qml", "ProviderIcon.qml", "Icons.js"):
            shutil.copy2(ROOT / name, plugin / name)
        for name in ("i18n", "assets"):
            shutil.copytree(ROOT / name, plugin / name)
        for name in ("Commons", "Ui", "services"):
            (work / name).symlink_to(Path("/usr/share/omarchy/shell") / name)
        # Main is the sole substituted component: all visible UI, icons, meter
        # logic and layout are the production files copied above, not a mockup.
        harnesses = [
            {"providerId": "opencode", "providerName": "OpenCode", "aiName": "ChatGPT",
             "detailText": "ChatGPT · gpt-6.1-sol", "limits": [
                 {"title": "5h window", "percent": 0.25}, {"title": "Weekly", "percent": 0.58}]},
            {"providerId": "codex", "providerName": "Codex", "aiName": "ChatGPT",
             "detailText": "ChatGPT · gpt-6-astra", "limits": [
                 {"title": "5h window", "percent": 0.25}, {"title": "Weekly", "percent": 0.58}]},
        ]
        accounts = [
            {"providerId": "demo-primary", "providerName": "ChatGPT · Personal", "aiName": "ChatGPT",
             "detailText": "OpenCode / Codex", "limits": [
                 {"title": "5h window", "percent": 0.25}, {"title": "Weekly", "percent": 0.58}]},
            {"providerId": "demo-secondary", "providerName": "DeepSeek · Work", "aiName": "DeepSeek",
             "detailText": "OpenCode", "balance": {"currency": "CNY", "remaining": 42.50}},
            {"providerId": "demo-third", "providerName": "ZAI · Personal", "aiName": "ZAI",
             "detailText": "OpenCode", "usageStatusText": "Usage lookup not supported"},
        ]
        for rows in (harnesses, accounts):
            for row in rows:
                for index, limit in enumerate(row.get("limits", [])):
                    limit["resetsAt"] = (datetime.now(timezone.utc) + timedelta(hours=2 if index == 0 else 96)).isoformat()
        stub = ('import QtQuick\nItem {\nproperty var settings: ({})\nproperty string collectionStatus: ""\n'
                'property var enabledProviders: ' + json.dumps(harnesses) + '\n'
                'property var accountProviders: ' + json.dumps(accounts) + '\n'
                'function refreshLimits() {}\n}\n')
        (plugin / "Main.qml").write_text(stub)
        shell = r'''
import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import "Demo" as Demo

ShellRoot {
  id: root
  property int step: 0
  PanelWindow {
    visible: true
    anchors { top: true; left: true; right: true }
    implicitHeight: 32
    color: "transparent"
    Demo.Panel { id: demo; x: 60 }
    Component.onCompleted: captureTimer.start()
  }
  Timer {
    id: captureTimer
    interval: 800
    onTriggered: {
      if (root.step === 0) {
        if (Quickshell.env("KONOUSAGE_PREVIEW_LIGHT") === "1") {
          Commons.Color.background = "#f5f5f5"
          Commons.Color.foreground = "#202020"
          Commons.Color.accent = "#303030"
          Commons.Color.popups.background = "#f5f5f5"
          Commons.Color.popups.border = "#b0b0b0"
        }
        demo.open()
        root.step = 1
        captureTimer.restart()
        return
      }
      for (var i = 0; i < demo.data.length; i++) {
        var panel = demo.data[i]
        if (panel.cardTarget !== undefined) {
          var card = panel.contentItem[0].parent.parent
          var file = root.step === 1 ? "harness.png" : "accounts.png"
          card.grabToImage(function(image) {
            if (!image.saveToFile(Qt.resolvedUrl(file).toString().replace(/^file:\/\//, ""))) {
              console.error("preview save failed")
              Qt.quit()
              return
            }
            if (root.step === 1) {
              root.step = 2
              demo.selectView("account")
              captureTimer.restart()
            } else { Qt.quit() }
          })
          return
        }
      }
      console.error("preview card not found")
      Qt.quit()
    }
  }
}
'''
        (work / "shell.qml").write_text(shell)
        # Keep Qt/Commons state isolated as well. The native palette still comes
        # from the user's theme, but no real client state is read by the stub.
        env = dict(os.environ, XDG_STATE_HOME=str(work / "state"), KONOUSAGE_PREVIEW_LIGHT="1" if light else "0")
        try:
            result = subprocess.run(["qs", "--no-color", "-p", str(work)], env=env,
                                    capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Native preview timed out:\n" + (error.stdout or b"").decode()
                               + (error.stderr or b"").decode()) from None
        if result.returncode or not all((work / f).is_file() for f in ("harness.png", "accounts.png")):
            raise RuntimeError("Native preview failed:\n" + result.stdout + result.stderr)
        font = subprocess.check_output(["fc-match", "-f", "%{file}", "sans"], text=True, timeout=5)
        subprocess.run(["magick", "montage", "-background", "#171717", "-fill", "#eeeeee",
                        "-font", font, "-pointsize", "12",
                        "-label", "HARNESS / DEMO DATA", str(work / "harness.png"),
                        "-label", "ACCOUNTS / DEMO DATA", str(work / "accounts.png"),
                        "-tile", "2x1", "-geometry", "+20+20", "-gravity", "north",
                        str(output)], check=True, timeout=20)
        print("Saved native Harness/Accounts preview with synthetic data:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--light", action="store_true", help="Exercise light-surface icon variants")
    parser.add_argument("--output", type=Path, default=ROOT / "preview.png")
    args = parser.parse_args()
    render(args.light, args.output)
