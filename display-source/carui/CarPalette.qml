import QtQuick 2.0

QtObject {
    property bool day: carController.dayTheme
    readonly property color text: day ? "#18283c" : "white"
    readonly property color secondary: day ? "#50627a" : "#aebcd4"
    readonly property color card: day ? "#f8fbff" : "#263249"
    readonly property color button: day ? "#dce6f2" : "#354460"
    readonly property color pressed: day ? "#b7cee9" : "#526795"
    readonly property color dock: day ? "#edf3f9" : "#dd090c14"
    readonly property color disabled: day ? "#9aabc0" : "#596071"
    readonly property color gradientTop: day ? "#e3edf8" : "#263657"
    readonly property color gradientMiddle: day ? "#d4e2f2" : "#17203a"
    readonly property color gradientBottom: day ? "#edf0f7" : "#382439"
    readonly property color tile: day ? "#c7d9ed" : "#324560"
    readonly property color oem: day ? "#bdcad9" : "#718294"
    readonly property color inactiveDot: day ? "#8294aa" : "#788193"
    readonly property color batteryCap: day ? "#657a94" : "#aeb5c5"
    readonly property color notice: day ? "#f5faff" : "#ed111a2c"
}
