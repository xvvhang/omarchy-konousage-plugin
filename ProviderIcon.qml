import QtQuick
import qs.Commons
import qs.Commons as Commons
import "Icons.js" as Icons

// Matches the built-in Agents plugin's surface-aware SVG/fallback behavior.
Item {
  id: root
  property string iconKey: ""
  property color surface: Commons.Color.popups.background
  property color foreground: Commons.Color.foreground
  property string fontFamily: Style.font.family
  property real size: Style.space(20)
  readonly property var candidates: Icons.candidates(iconKey, Icons.lightSurface(surface.r, surface.g, surface.b))
  readonly property string candidatesKey: candidates.join("\n")
  property int candidateIndex: 0
  onCandidatesKeyChanged: candidateIndex = 0
  width: size
  height: size

  Image {
    id: mark
    anchors.fill: parent
    source: root.candidateIndex < root.candidates.length ? Qt.resolvedUrl(root.candidates[root.candidateIndex]) : ""
    sourceSize.width: root.size * 2
    sourceSize.height: root.size * 2
    fillMode: Image.PreserveAspectFit
    onStatusChanged: if (status === Image.Error && root.candidateIndex < root.candidates.length) {
      var failedSource = source.toString()
      Qt.callLater(function() {
        if (mark.status === Image.Error && mark.source.toString() === failedSource) root.candidateIndex++
      })
    }
  }

  Text {
    textFormat: Text.PlainText
    anchors.centerIn: parent
    visible: mark.status !== Image.Ready
    text: "󱚣"
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: root.size
  }
}
