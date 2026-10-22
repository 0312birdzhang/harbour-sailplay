import QtQuick 2.0
import Sailfish.Silica 1.0

Page {
    id: aboutPage
    objectName: "sailplayAboutPage"
    allowedOrientations: Orientation.All
    SilicaFlickable {
        anchors.fill: parent
        contentHeight: content.height
        Column {
            id: content
            width: aboutPage.width
            spacing: Theme.paddingMedium
            PageHeader { title: qsTranslate("Sailplay", "About") }
            Image {
                anchors.horizontalCenter: parent.horizontalCenter
                width: Theme.itemSizeExtraLarge; height: width
                source: "file:///opt/sailplay/carui/harbour-sailplay.png"
                fillMode: Image.PreserveAspectFit
            }
            Label {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Sailplay"
                font.pixelSize: Theme.fontSizeExtraLarge
                color: Theme.highlightColor
            }
            Label {
                objectName: "sailplayVersion"
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                horizontalAlignment: Text.AlignHCenter
                text: qsTranslate("Sailplay", "Version %1").arg(carController.packageVersion)
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
            }
            Label {
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                wrapMode: Text.WordWrap
                text: qsTranslate("Sailplay", "Wireless CarPlay for SailfishOS. Projects a dedicated car interface over Bluetooth and Wi-Fi, with touch input, app launching and a map, weather and music dashboard.")
            }
            Button {
                anchors.horizontalCenter: parent.horizontalCenter
                text: qsTranslate("Sailplay", "Source code")
                onClicked: Qt.openUrlExternally("https://github.com/0312birdzhang/harbour-sailplay")
            }
            Label {
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                wrapMode: Text.WordWrap
                text: qsTranslate("Sailplay", "License: %1").arg("GPL-3.0-or-later")
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.secondaryColor
            }
            SectionHeader { text: qsTranslate("Sailplay", "Acknowledgements") }
            Label {
                x: Theme.horizontalPageMargin; width: parent.width - 2 * x
                wrapMode: Text.WordWrap
                text: qsTranslate("Sailplay", "Thanks to the projects that made Sailplay possible. Upstream components retain their respective licenses and copyright notices.")
                font.pixelSize: Theme.fontSizeSmall
            }
            Repeater {
                objectName: "sailplayAcknowledgements"
                model: [
                    { name: "Sailife", url: "https://github.com/0312birdzhang/harbour-sailife", detail: qsTranslate("Sailplay", "Car launcher and projection pipeline") },
                    { name: "Imira", url: "https://github.com/JimKnopfIoT/harbour-imira", detail: qsTranslate("Sailplay", "Virtual display, capture and audio latency") },
                    { name: "sailfish-weather", url: "https://github.com/sailfishos/sailfish-weather", detail: qsTranslate("Sailplay", "Weather components and Events view reference") },
                    { name: "zzmusic", url: "https://github.com/ZeroX-S/zzmusic", detail: qsTranslate("Sailplay", "Music artwork handling") },
                    { name: "DiPlay", url: "https://github.com/shihabal3amri/DiPlay", detail: qsTranslate("Sailplay", "CarPlay receiver and interoperability testing") },
                    { name: "Qt", url: "https://www.qt.io/", detail: qsTranslate("Sailplay", "Application UI and music controls") },
                    { name: "Sailfish Silica", url: "https://docs.sailfishos.org/Reference/Silica/", detail: qsTranslate("Sailplay", "Application UI and music controls") },
                    { name: "Amber.Mpris", url: "https://github.com/sailfishos/amber-mpris", detail: qsTranslate("Sailplay", "Application UI and music controls") },
                    { name: "x264", url: "https://www.videolan.org/developers/x264.html", detail: qsTranslate("Sailplay", "H.264 video encoding") },
                    { name: "FFmpeg", url: "https://ffmpeg.org/", detail: qsTranslate("Sailplay", "AAC audio encoding") },
                    { name: "PulseAudio", url: "https://www.freedesktop.org/wiki/Software/PulseAudio/", detail: qsTranslate("Sailplay", "Audio routing and monitor capture") },
                    { name: "BlueZ", url: "https://www.bluez.org/", detail: qsTranslate("Sailplay", "Bluetooth and Wi-Fi integration") },
                    { name: "ConnMan", url: "https://git.kernel.org/pub/scm/network/connman/connman.git/", detail: qsTranslate("Sailplay", "Bluetooth and Wi-Fi integration") },
                    { name: "OpenSSL", url: "https://www.openssl.org/", detail: qsTranslate("Sailplay", "Cryptography and development tests") },
                    { name: "cryptography", url: "https://cryptography.io/", detail: qsTranslate("Sailplay", "Cryptography and development tests") }
                ]
                delegate: Column {
                    x: Theme.horizontalPageMargin
                    width: content.width - 2 * x
                    spacing: Theme.paddingSmall
                    Label {
                        width: parent.width
                        textFormat: Text.StyledText
                        font.pixelSize: Theme.fontSizeExtraSmall
                        wrapMode: Text.WordWrap
                        linkColor: Theme.highlightColor
                        font.letterSpacing: 2;
                        text: "<a href=\"" + modelData.url + "\">" + modelData.name + "</a>"
                        onLinkActivated: Qt.openUrlExternally(link)
                    }

                    Label {
                        width: parent.width
                        text: modelData.detail
                        wrapMode: Text.WordWrap
                        font.pixelSize: Theme.fontSizeSmall
                        color: Theme.secondaryColor
                    }
                    Item { width: 1; height: Theme.paddingSmall }
                }
            }
            Item { width: 1; height: Theme.paddingLarge }
        }
        VerticalScrollDecorator { }
    }
}
