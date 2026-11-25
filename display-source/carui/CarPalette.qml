import QtQuick 2.0
import Sailfish.Silica 1.0 as Silica
import Nemo.Configuration 1.0

QtObject {
    property bool day: carController.dayTheme

    // When the car follows the phone ambience, the screen takes the
    // ambience's own application background and builds its surfaces from the
    // ambience accent. With the headlight or scheduled themes, which may
    // disagree with the phone's light or dark scheme, the fixed day and night
    // colours below are used instead.
    readonly property bool ambience: carController.followAmbience === true
    property ConfigurationValue appBackground: ConfigurationValue {
        key: "/desktop/jolla/background/portrait/app_picture_filename"
        defaultValue: ""
    }
    readonly property url wallpaper: ambience && appBackground.value ? "file://" + appBackground.value : ""
    readonly property color ambienceBase: day ? "#f2f5f7" : "#15181c"
    readonly property color ambienceCard: Qt.tint(ambienceBase, Qt.rgba(highlightColor.r, highlightColor.g, highlightColor.b, day ? 0.10 : 0.12))
    readonly property color ambienceButton: Qt.tint(ambienceCard, Qt.rgba(text.r, text.g, text.b, day ? 0.10 : 0.14))

    // Outside ambience mode a day theme can sit on a dark phone ambience,
    // where Silica's slider would be unreadable: the flat bar is drawn then.
    readonly property bool flatSeekBar: day && !ambience
    readonly property color background: ambience ? ambienceCard : day ? "#e3edf8" : "#17203a"
    readonly property color positive: "#28774e"
    readonly property color negative: "#963b48"
    readonly property color actionText: "white"
    readonly property color text: day ? "#18283c" : "white"
    readonly property color secondary: day ? "#50627a" : "#aebcd4"
    // Opaque: panels that must hide what lies under them.
    readonly property color card: ambience ? ambienceCard : day ? "#f8fbff" : "#263249"
    // Panels laid directly on the screen background: a veil over the
    // ambience picture, the plain card colour otherwise.
    readonly property color surface: !ambience ? card : day ? Qt.rgba(1, 1, 1, 0.5) : Qt.rgba(0, 0, 0, 0.28)
    readonly property color button: ambience ? ambienceButton : day ? "#dce6f2" : "#354460"
    // The pressed state carries the ambience accent, as Silica controls do.
    readonly property color pressed: Qt.tint(button, Qt.rgba(highlightColor.r, highlightColor.g, highlightColor.b, 0.35))
    readonly property color dock: ambience ? "transparent" : day ? "#edf3f9" : "#dd090c14"
    readonly property color disabled: day ? "#9aabc0" : "#596071"
    readonly property color gradientTop: ambience ? ambienceCard : day ? "#e3edf8" : "#263657"
    readonly property color gradientMiddle: ambience ? ambienceCard : day ? "#d4e2f2" : "#17203a"
    readonly property color gradientBottom: ambience ? ambienceCard : day ? "#edf0f7" : "#382439"
    readonly property color tile: ambience ? ambienceButton : day ? "#c7d9ed" : "#324560"
    readonly property color oem: day ? "#bdcad9" : "#718294"
    readonly property color inactiveDot: day ? "#8294aa" : "#788193"
    readonly property color batteryCap: day ? "#657a94" : "#aeb5c5"
    readonly property color notice: ambience ? ambienceCard : day ? "#f5faff" : "#ed111a2c"

    // Ambience roles. Each carries the name of the Silica Theme colour it
    // stands for. The two accents follow the phone ambience, adapted to the
    // car's own day or night scheme, which may differ from the phone's.
    readonly property int scheme: day ? Silica.Theme.DarkOnLight : Silica.Theme.LightOnDark
    readonly property color primaryColor: text
    readonly property color secondaryColor: secondary
    readonly property color highlightColor: Silica.Theme.highlightFromColor(Silica.Theme.highlightColor, scheme)
    // Silica's own secondary highlight is too pale for the day surfaces, so
    // the accent is drawn towards the secondary text colour instead.
    readonly property color secondaryHighlightColor: Qt.tint(highlightColor, Qt.rgba(secondary.r, secondary.g, secondary.b, 0.4))
    readonly property color highlightBackgroundColor: button
    readonly property color highlightDimmerColor: background
    readonly property color overlayBackgroundColor: card
    // The halo Silica draws behind a glow on light ambiences.
    readonly property color glowBackgroundColor: day ? Silica.Theme.highlightDimmerFromColor(Silica.Theme.highlightColor, scheme) : "transparent"
}
