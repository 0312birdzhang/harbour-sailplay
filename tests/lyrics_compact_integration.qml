import QtQuick 2.0

Item {
    width: 600; height: 400
    QtObject {
        id: carController
        signal playerLyricsAvailable(string key, var rows, int offsetMs, string plainText)
        function playerTrackId(value) { return "" }
        function requestPlayerLyrics(service, track, key) {}
    }
    LyricsPanel {
        id: lyrics
        width: 540; height: 130
        palette: ({text:"white", secondary:"gray"})
        lines: [[0,"first"],[1,"second"],[2,"third"],[3,"fourth"],
                [4,"a long lyric with translation\ntranslated line"],[5,"sixth"],[6,"seventh"],[7,"last"]]
    }
    function find(item, name) {
        if (item.objectName === name) return item
        var children = item.children || []
        for (var i=0; i<children.length; ++i) {
            var result = find(children[i], name)
            if (result) return result
        }
        return null
    }
    function check(ok, message) {
        if (!ok) { console.log("LYRICS_COMPACT_FAIL", message); Qt.quit() }
        return ok
    }
    Timer {
        interval: 100; running: true; repeat: true
        property int stage: 0
        onTriggered: {
            if (stage > 0) {
                var compact = find(lyrics, "compactLyrics")
                if (!check(lyrics.compactLines.length === 4 && compact.y >= 12
                        && compact.y + compact.height <= lyrics.height - 12, "four rows at height " + lyrics.height)) return
            }
            if (stage < 3) {
                lyrics.height = [130, 240, 400][stage]
                lyrics.positionSeconds = [0, 4, 7][stage]
                stage++; return
            }
            var group = find(lyrics,"compactLyrics")
            if (!check(lyrics.compactLines.length === 4, "row count")) return
            if (!check(group.y >= 12 && group.y + group.height <= lyrics.height - 12, "vertical padding")) return
            for (var i=0; i<4; ++i) {
                var row = find(lyrics,"compactLyricLine_" + i)
                if (!check(row && row.text.indexOf("\n") < 0 && row.height > row.font.pixelSize, "bounded single line")) return
            }
            if (!check(lyrics.compactStart === 4 && lyrics.compactLines[3][1] === "last", "end window")) return
            lyrics.lines = []; lyrics.plainText = "1\n2\n3\n4\n5\n6"
            var plain = find(lyrics,"compactPlainLyrics")
            if (!check(plain.maximumLineCount === 4, "plain lyrics bounded")) return
            console.log("LYRICS_COMPACT_PASS four-rows padding translation end-window plain-text")
            Qt.quit()
        }
    }
}
