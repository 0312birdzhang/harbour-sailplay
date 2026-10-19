#pragma once
// Half-open local-time interval; also supports a daytime period across midnight.
inline bool sailplayDayAt(int minute, int dayStart, int nightStart) {
    return dayStart < nightStart ? minute >= dayStart && minute < nightStart
                                : minute >= dayStart || minute < nightStart;
}
