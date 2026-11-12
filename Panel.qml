import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Icons.js" as Icons

Panel {
  id: root
  moduleName: "konochi.konousage"
  ipcTarget: "konochi.konousage"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color urgent: bar ? bar.urgent : Commons.Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  property string viewMode: "harness"
  property double nowMs: Date.now()
  readonly property var rows: viewMode === "account" ? usage.accountProviders : usage.enabledProviders
  readonly property bool alarming: rows.some(function(row) {
    return (row.limits || []).some(function(limit) { return Number(limit.percent) >= 0.9 })
  })

  Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
  Main { id: usage; settings: root.settings }

  function selectView(mode) {
    if (viewMode === mode) return
    viewMode = mode
    list.contentY = 0
  }

  function scrollBy(amount) {
    list.contentY = Math.max(0, Math.min(Math.max(0, list.contentHeight - list.height), list.contentY + amount))
  }

  function quotaText(limit) {
    var left = Math.round((1 - Math.max(0, Math.min(1, Number(limit.percent)))) * 100)
    return strings.t("quota.remaining").arg(left)
  }

  function resetText(limit) {
    var ms = new Date(limit.resetsAt || "").getTime() - nowMs
    if (!(ms > 0)) return ""
    var minutes = Math.max(1, Math.ceil(ms / 60000))
    var hours = Math.floor(minutes / 60)
    var days = Math.floor(hours / 24)
    var duration = days > 0 ? days + "d " + hours % 24 + "h"
      : hours > 0 ? hours + "h " + minutes % 60 + "m" : minutes + "m"
    return strings.t("quota.reset").arg(duration)
  }

  function statusText(row) {
    var status = String(row.usageStatusText || "")
    var keys = {
      "Usage lookup not supported": "status.unsupported",
      "Current AI unknown": "status.unknown",
      "Current account unavailable": "status.account",
      "Sign-in unavailable": "status.signin",
      "Unable to refresh": "status.refresh",
      "Collection timed out": "status.timeout",
      "Collection failed": "status.failed",
      "No quota windows reported": "status.empty"
    }
    return keys[status] ? strings.t(keys[status]) : status
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  onOpenedChanged: if (root.opened) {
    root.nowMs = Date.now()
    usage.refreshLimits()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  Timer {
    interval: 30000
    running: root.opened
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { usage.refreshLimits(); return "ok" }
    function next(): string { root.scrollBy(Style.space(100)); return "ok" }
    function view(mode: string): string {
      if (mode !== "account" && mode !== "harness") return "Expected harness or account"
      root.selectView(mode)
      return "ok"
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󱚣"
    active: root.alarming
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.selectView(root.viewMode === "harness" ? "account" : "harness")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.selectView(dx > 0 ? "account" : "harness")
        if (dy !== 0) root.scrollBy(dy * Style.space(56))
      }
      onActivateRequested: usage.refreshLimits()
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "r" || t === "R") usage.refreshLimits()
        if (t === "v" || t === "V") root.selectView(root.viewMode === "harness" ? "account" : "harness")
      }

      Flickable {
        id: list
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: content
          width: list.width
          spacing: Style.space(12)

          Row {
            width: parent.width
            spacing: Style.spacing.md
            Repeater {
              model: ["harness", "account"]
              Button {
                required property string modelData
                width: (content.width - Style.spacing.md) / 2
                text: strings.t(modelData === "harness" ? "view.harness" : "view.account")
                selected: root.viewMode === modelData
                bordered: true
                foreground: root.foreground
                fontFamily: root.fontFamily
                onClicked: root.selectView(modelData)
              }
            }
          }

          Repeater {
            model: root.rows
            Column {
              id: usageRow
              required property var modelData
              width: content.width
              spacing: Style.space(6)

              PanelSeparator { foreground: root.foreground }

              Row {
                width: parent.width
                spacing: Style.space(10)

                ProviderIcon {
                  id: rowIcon
                  anchors.verticalCenter: parent.verticalCenter
                  iconKey: Icons.iconKey(root.viewMode, usageRow.modelData.providerId, usageRow.modelData.aiName)
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                }

                Column {
                  width: parent.width - rowIcon.width - parent.spacing
                  spacing: Style.space(3)

                  Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: usageRow.modelData.providerName
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    elide: Text.ElideRight
                  }

                  Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: usageRow.modelData.detailText || ""
                    visible: text !== ""
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WrapAnywhere
                  }
                }
              }

              Repeater {
                model: usageRow.modelData.limits || []
                Column {
                  id: quotaRow
                  required property var modelData
                  width: usageRow.width
                  spacing: Style.space(3)
                  Row {
                    width: parent.width
                    Text {
                      textFormat: Text.PlainText
                      width: parent.width - remaining.implicitWidth - Style.space(10)
                      text: String(quotaRow.modelData.title || quotaRow.modelData.label || "")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                    Text {
                      id: remaining
                      textFormat: Text.PlainText
                      text: root.quotaText(quotaRow.modelData)
                      color: Number(quotaRow.modelData.percent) >= 0.9 ? root.urgent : root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                  Rectangle {
                    id: quotaTrack
                    width: parent.width
                    height: Math.max(Style.space(4), Math.round(Style.spacing.controlHeight * 0.14))
                    radius: height / 2
                    color: Style.selectedFillFor(root.foreground, Commons.Color.accent)

                    Rectangle {
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                      width: quotaTrack.width * Math.max(0, Math.min(1, 1 - Number(quotaRow.modelData.percent)))
                      height: parent.height
                      radius: height / 2
                      color: Number(quotaRow.modelData.percent) >= 0.9 ? root.urgent : root.foreground

                      Behavior on width {
                        NumberAnimation { duration: Style.duration(160); easing.type: Easing.OutCubic }
                      }
                    }
                  }
                  Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: root.resetText(quotaRow.modelData)
                    visible: text !== ""
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }

              Text {
                textFormat: Text.PlainText
                visible: !!usageRow.modelData.balance
                width: parent.width
                text: usageRow.modelData.balance ? strings.t("balance.remaining")
                  .arg(usageRow.modelData.balance.currency)
                  .arg(Number(usageRow.modelData.balance.remaining).toFixed(2)) : ""
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Text {
                textFormat: Text.PlainText
                width: parent.width
                text: root.statusText(usageRow.modelData)
                visible: text !== ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            visible: root.rows.length === 0
            text: usage.collectionStatus !== "" ? root.statusText({usageStatusText: usage.collectionStatus}) : strings.t("view.empty")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            wrapMode: Text.WordWrap
          }

          Button {
            width: parent.width
            text: strings.t("action.refresh")
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: usage.refreshLimits()
          }
        }
      }
    }
  }
}
