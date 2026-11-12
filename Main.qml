import QtQuick
import Quickshell
import Quickshell.Io
import "RefreshState.js" as RefreshState

// A single atomic inventory keeps harness/account associations in the same scan.
Item {
  id: root
  visible: false
  property var settings: ({})
  readonly property string home: Quickshell.env("HOME") || ""
  readonly property string usageDir: (Quickshell.env("XDG_STATE_HOME") || home + "/.local/state") + "/omarchy/ai-usage"
  property var inventory: ({})
  readonly property string syncStatusText: ""
  property bool pendingRefresh: false
  property string collectionStatus: ""
  readonly property int refreshIntervalSec: Math.max(60, Number(settings.refreshIntervalSec || 300))

  FileView {
    id: inventoryFile
    path: root.usageDir + "/inventory.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var parsed = JSON.parse(text())
        if (parsed.schemaVersion === 2) root.inventory = parsed
      } catch (e) { console.warn("konousage", "Invalid usage inventory") }
    }
  }

  Process {
    id: updateProcess
    command: ["python3", "-B", Qt.resolvedUrl("collect.py").toString().replace(/^file:\/\//, "")]
    onExited: function(exitCode, exitStatus) {
      var next = RefreshState.settle(exitCode, exitStatus, root.pendingRefresh)
      root.collectionStatus = next.status
      root.pendingRefresh = false
      if (root.collectionStatus === "") inventoryFile.reload()
      if (next.retry) Qt.callLater(root.refreshLimits)
    }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refreshLimits()
  }

  function refreshAll(force) { refreshLimits() }
  function refreshLimits() {
    var next = RefreshState.request(updateProcess.running)
    pendingRefresh = next.queue
    if (next.start) updateProcess.running = true
  }

  function providerEnabled(id) {
    return !settings.providers || !settings.providers[id] || settings.providers[id].enabled !== false
  }

  function display(record, id, name, detail) {
    var result = Object.assign({}, record)
    result.providerId = id
    result.providerName = name
    result.detailText = detail
    if (root.collectionStatus !== "") {
      result.usageStatusText = root.collectionStatus
      result.authHelpText = "Collection did not complete. Displaying cached values, not a confirmed current account association."
    }
    return result
  }

  readonly property var accountProviders: {
    var result = []
    var accounts = inventory.accounts || []
    for (var i = 0; i < accounts.length; i++) {
      var account = accounts[i]
      var sources = account.harnesses || []
      // Include saved inactive accounts, but respect disabled harnesses.
      if (!sources.some(function(name) { return root.providerEnabled(name.toLowerCase()) })) continue
      var ai = String(account.aiName || "AI")
      var label = String(account.name || "")
      if (label.indexOf(ai + " · ") === 0) label = label.slice(ai.length + 3)
      var accountLabel = label && label !== ai ? label : account.id.slice(0, 6)
      result.push(display(account, account.id, ai + " · " + accountLabel,
        sources.join(" / ")))
    }
    return result
  }

  readonly property var enabledProviders: {
    var result = []
    var accounts = inventory.accounts || []
    var harnesses = inventory.harnesses || []
    for (var i = 0; i < harnesses.length; i++) {
      var harness = harnesses[i]
      if (!providerEnabled(harness.id.split(":")[0])) continue
      var account = accounts.find(function(a) { return a.id === harness.accountKey })
      var ai = String(harness.aiName || "")
      var model = String(harness.modelName || "")
      result.push(display(account || harness, harness.id, harness.name,
        ai + (ai && model ? " · " : "") + model))
    }
    return result
  }

  function formatTokenCount(n) {
    if (!n) return "0"
    if (n >= 1e9) return (n / 1e9).toFixed(1) + "B"
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M"
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K"
    return String(n)
  }

  function friendlyModelName(id) { return String(id || "Unknown") }
}
