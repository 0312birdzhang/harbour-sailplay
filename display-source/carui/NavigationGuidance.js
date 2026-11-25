.pragma library

function distance(meters) {
    return meters >= 1000 ? (meters / 1000).toFixed(1) + " km" : Math.round(meters) + " m"
}

function symbol(maneuver, drivingSide, exitNumber) {
    var symbols = {
        "continue": "↑", "slight-left": "↖", "slight-right": "↗",
        "turn-left": "←", "turn-right": "→", "sharp-left": "↙", "sharp-right": "↘",
        "exit-left": "↙", "exit-right": "↘", "uturn": "↶",
        "roundabout-enter": "⟳", "roundabout-exit": "⟳", "roundabout-continue": "⟳", "arrive": "⚑"
    }
    var result = symbols[maneuver] || ""
    if (maneuver === "uturn" && drivingSide === "left") result = "↷"
    if (maneuver.indexOf("roundabout-") === 0 && drivingSide === "left") result = "⟲"
    if (maneuver === "roundabout-exit" && exitNumber > 0) result += " " + exitNumber
    return result
}
