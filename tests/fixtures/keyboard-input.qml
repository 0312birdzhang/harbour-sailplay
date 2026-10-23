import QtQuick 2.0
import QtQuick.Window 2.0
Window {
 width:1780; height:720; visible:true; title:"Sailplay keyboard test"; color:"#253040"
 Rectangle { x:80; y:60; width:900; height:90; color:"white"
  TextInput { id:field; anchors.fill:parent; anchors.margins:10; font.pixelSize:40; color:"black"; focus:true
   onTextChanged: console.log("SYNTHETIC_CODEPOINT="+(text.length?text.charCodeAt(0):0))
   Keys.onReturnPressed: { opener.stop(); Qt.inputMethod.hide(); console.log("SYNTHETIC_RETURN") }
   MouseArea { anchors.fill:parent; onClicked:{field.forceActiveFocus();Qt.inputMethod.show()} }
  }
 }
 Rectangle { x:80;y:180;width:300;height:80;color:"#708090"
  MouseArea { anchors.fill:parent;onClicked:{field.focus=false;Qt.inputMethod.hide();console.log("SYNTHETIC_HIDE")} }
 }
 Connections { target:Qt.inputMethod; onVisibleChanged:{console.log("KEYBOARD_VISIBLE="+Qt.inputMethod.visible);if(Qt.inputMethod.visible)opener.stop()} }
 Timer { id:opener; interval:800; running:true; repeat:true; onTriggered:{field.forceActiveFocus();Qt.inputMethod.show()} }
}
