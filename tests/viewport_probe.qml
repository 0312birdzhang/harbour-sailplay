import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
Silica.ApplicationWindow {
 property int silicaWidth: Silica.Screen.width
 property int silicaHeight: Silica.Screen.height
 property int pageWidth: pageStack.currentPage ? pageStack.currentPage.width : 0
 property int pageHeight: pageStack.currentPage ? pageStack.currentPage.height : 0
 allowedOrientations: Silica.Orientation.Landscape
 cover: null
 initialPage: Component { Silica.Page { allowedOrientations: Silica.Orientation.Landscape; Rectangle { anchors.fill: parent; color: "#263249"; Text { anchors.centerIn: parent; text: "Viewport sizing check"; color: "white"; font.pixelSize: 32 } } } }
}
