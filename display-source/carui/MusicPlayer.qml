import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Amber.Mpris 1.0

// Both car layouts share one controller, never a projected player window.
Item {
    id: controls
    property alias mprisController: player
    property url albumArtSource
    readonly property real _squareSize: 88
    readonly property real headerHeight: 164
    signal clicked()
    height: headerHeight + 24 + _squareSize
    visible: !!player.currentService
    MprisController { id: player }
    Rectangle {
        width: 148; height: 148; radius: 16; color: "#354460"
        Image {
            anchors.fill: parent; anchors.margins: 4
            source: controls.albumArtSource
            fillMode: Image.PreserveAspectFit
        }
        Text { anchors.centerIn: parent; text: "♫"; color: "#aebcd4"; font.pixelSize: 64; visible: !controls.albumArtSource }
    }
    Column {
        x: 172; width: Math.max(0, parent.width - x); spacing: 12
        Text {
            width: parent.width; color: "white"; font.pixelSize: 34
            elide: Text.ElideRight
            text: player.metaData.title || player.identity || ""
        }
        Text {
            width: parent.width; color: "#aebcd4"; font.pixelSize: 26
            elide: Text.ElideRight
            text: (player.metaData.contributingArtist || "").toString()
        }
        Text {
            width: parent.width; color: "#aebcd4"; font.pixelSize: 22
            elide: Text.ElideRight; text: player.identity || ""
        }
    }
    MouseArea { width: parent.width; height: controls.headerHeight; onClicked: controls.clicked() }
    Row {
        y: controls.headerHeight + 24; width: parent.width
        Repeater {
            model: 3
            Item {
                width: controls.width / 3; height: controls._squareSize
                Silica.IconButton {
                    anchors.centerIn: parent; width: controls._squareSize; height: width
                    enabled: index === 0 ? player.canGoPrevious : index === 2 ? player.canGoNext
                              : player.playbackStatus === Mpris.Playing ? player.canPause : player.canPlay
                    opacity: enabled ? 1 : 0.35
                    icon.source: index === 0 ? "image://theme/icon-m-simple-previous"
                                 : index === 2 ? "image://theme/icon-m-simple-next"
                                 : player.playbackStatus === Mpris.Playing ? "image://theme/icon-m-simple-pause"
                                 : "image://theme/icon-m-simple-play"
                    onClicked: {
                        if (index === 0) player.previous()
                        else if (index === 2) player.next()
                        else player.playPause()
                    }
                }
            }
        }
    }
}
