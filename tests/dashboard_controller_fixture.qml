import QtQuick 2.0

QtObject {
    property bool dayTheme: false
    property var status: ({})
    property var tiles: []
    property var dockApps: []
    property string currentApp: ""
    property bool dashboardActive: true
    property bool musicActive: false
    property bool showMusicLyrics: true
    property bool returnToDashboard: true
    property string dashboardMapApp: ""
    property bool dashboardNavigationTemplate: false
    property bool contentActive: false
    property bool navigationActive: false
    property var content: null
    property var dashboardWeather: ({})
    property string dashboardWeatherLocation: ""
    property bool hasRememberedMusic: false
    property string lastMusicName: "Test music"
    property string lastMusicApp: ""
    property string musicError: ""
    property bool musicContentAvailable: false
    property QtObject navigation: QtObject {
        property bool ready: true
        property bool navigating: false
        property var lastRouteOverview: ({})
        property string name: "Test navigation"
        property bool mapAvailable: false
        property string error: ""
        property var guidance: ({state: "idle"})
        property var mapBrowser: ({})
        property bool mapBrowseBusy: false
        function configureMap(width, height) {}
    }
    signal artworkAvailable(string key, url localUrl)
    signal musicAppRequested(string appId)
    signal playerPlaybackFinished(string service, bool success)
    signal playerPositionAvailable(string service, string trackKey, real seconds)
    signal playerLyricsAvailable(string key, var rows, int offsetMs, string plainText)
    signal playerQueueAvailable(string service, var items, int index, string revision, bool loading, bool error)
    function restoreShellView() {}
    function availableApps(showAll) { return [] }
    function ensureMusicBackend() { return false }
    function isLocalMusicService(service) { return false }
    function musicAppIcon(appId) { return "" }
    function musicServiceForApp(app, services) { return "" }
    function preferredMusicService(services) { return "" }
    function rememberMusicPlayer(service) {}
    function artworkSource(art, track) { return "" }
    function requestPlayerPosition(service, key) {}
    function playerTrackId(value) { return String(value || "") }
    function requestPlayerLyrics(service, track, key) {}
    function playerQueueSupported(service) { return true }
    function requestPlayerQueue(service) {}
}
