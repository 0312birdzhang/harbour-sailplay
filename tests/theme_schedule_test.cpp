#include "../display-source/carui/themeschedule.h"
#include <cassert>
int main() {
    assert(!sailplayDayAt(0,420,1140));
    assert(!sailplayDayAt(419,420,1140));
    assert(sailplayDayAt(420,420,1140));
    assert(sailplayDayAt(1139,420,1140));
    assert(!sailplayDayAt(1140,420,1140));
    assert(!sailplayDayAt(1439,420,1140));
    assert(sailplayDayAt(0,1200,360));
    assert(sailplayDayAt(359,1200,360));
    assert(!sailplayDayAt(360,1200,360));
    assert(!sailplayDayAt(1199,1200,360));
    assert(sailplayDayAt(1200,1200,360));
    assert(sailplayDayAt(1439,1200,360));
}
